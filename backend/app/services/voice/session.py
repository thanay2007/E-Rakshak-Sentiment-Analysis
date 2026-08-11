"""The session — Rapida's `OnPacket` router and Talk loop, in one place.

Ported from `adapters/internal/callback_generic.go` (the central packet
router), `talking.go` (the receive loop), `session_generic.go` (lifecycle) and
`behaviors_generic.go` (greeting, idle, max duration).

Everything that happens in a conversation happens because `on_packet` decided
it should. Components emit packets; this dispatches them; nothing else knows
about anything else. The full path a spoken question takes:

    UserAudioReceived                    a 20 ms frame from the browser
      → DenoiseAudio       → denoiser
      → DenoisedAudio      → VAD
      → VadSpeechActivity  → interruption check, then gate
      → SpeechToTextAudio  → recogniser
      → SpeechToText       → end-of-speech detector
      → EndOfSpeech        → the assistant
      → LLMResponseDelta   → aggregator
      → TextToSpeechText   → normalizer → synthesiser
      → TextToSpeechAudio  → the browser

Each arrow is one branch below, and the pipeline can be understood by reading
them in order.

**The safety boundary is unchanged by any of this.** The assistant this session
calls is the same `services/assistant` package the typed endpoint uses, with
the same refusal check, the same rank-filtered tools, the same audit write.
Voice is a transport. It does not widen what may be asked, and adding a
microphone did not add a capability — `guard.refusal_for` runs on the
transcript before the agent sees it, exactly as it runs on typed input.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from sqlmodel import Session as DbSession

from app.config import settings
from app.models import User
from app.services.assistant import agent, guard, tools as assistant_tools
from app.services.audit import log_action
from app.services.voice import aggregator as aggregator_module
from app.services.voice import denoiser as denoiser_module
from app.services.voice import end_of_speech as eos_module
from app.services.voice import vad as vad_module
from app.services.voice.audio import FrameBuffer, normalise_inbound
from app.services.voice.normalizer import OutputNormalizer
from app.services.voice.state import ConversationState, TurnState
from app.services.voice.wake import WakeWord
from app.services.voice.telemetry import Telemetry
from app.services.voice.transformer import stt as stt_module
from app.services.voice.transformer import tts as tts_module
from app.services.voice.types import FRAME_MS
from app.services.voice.types import (DenoiseAudioPacket, DenoisedAudioPacket,
                                      EndOfSpeechPacket, ExecuteLLMPacket,
                                      InitializationCompletedPacket,
                                      InjectMessagePacket,
                                      InterimEndOfSpeechPacket,
                                      InterruptionDetectedPacket,
                                      LLMNavigatePacket, LLMResponseDeltaPacket,
                                      LLMResponseDonePacket, LLMToolInvokedPacket,
                                      Packet, PipelineErrorPacket,
                                      SpeechToTextAudioPacket, SpeechToTextPacket,
                                      TextToSpeechAudioPacket,
                                      TextToSpeechDonePacket,
                                      TextToSpeechTextPacket, TurnChangePacket,
                                      UserAudioReceivedPacket,
                                      UserTextReceivedPacket,
                                      VadSpeechActivityPacket, WakeStatePacket,
                                      new_context_id)

log = logging.getLogger("sentinel.voice.session")


@dataclass
class SessionConfig:
    """Everything a session needs that is not a live object."""
    language: str = "en-IN"
    page: str = ""
    stt_provider: str = ""
    tts_provider: str = ""
    vad_provider: str = ""
    denoiser_provider: str = ""
    #: The browser's capture rate. Almost always 48000; asked for rather than
    #: assumed, because getting it wrong transcribes a chipmunk.
    input_sample_rate: int = 16_000
    #: None means "whatever the deployment configured"; "" means "say nothing",
    #: which is what a reconnect asks for.
    greeting: str | None = None
    idle_timeout: float = 0.0
    max_session_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)


class VoiceSession:
    """One officer, one microphone, one websocket.

    `emit` is how packets leave for the client. Everything else is internal.
    """

    def __init__(self, *, user: User, db: DbSession, config: SessionConfig,
                 emit) -> None:
        self.user = user
        self.db = db
        self.config = config
        self._emit = emit

        self.state = ConversationState()
        self.telemetry = Telemetry()
        self.normalizer = OutputNormalizer()
        self._frames = FrameBuffer()
        self._closed = False
        self._turn: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        #: Silence accumulated since the officer last said something, and the
        #: guard that stops it starting a second transcription during the
        #: first. Both only matter for a batch recogniser — see `_on_silence`.
        self._silence_ms = 0.0
        self._flushing = False
        self._eos_silence_ms = settings.VOICE_EOS_SILENCE_SECONDS * 1000

        # Components are constructed with `self.on_packet`, which is the entire
        # wiring. None of them holds a reference to another.
        self.denoiser = denoiser_module.create(
            self.on_packet, config.denoiser_provider or settings.VOICE_DENOISER)
        self.vad = vad_module.create(
            self.on_packet, config.vad_provider or settings.VOICE_VAD_PROVIDER)
        self.stt = stt_module.create(
            self.on_packet, config.stt_provider, language=config.language)
        self.tts = tts_module.create(
            self.on_packet, config.tts_provider, language=config.language)
        self.eos = eos_module.create(
            self.on_packet, silence_timeout=settings.VOICE_EOS_SILENCE_SECONDS)
        self.aggregator = aggregator_module.create(self.on_packet)
        # Per session, so an officer reconnecting mid-shift starts a fresh
        # conversation rather than inheriting an open follow-up window from a
        # session that ended ten minutes ago.
        self.wake = WakeWord()

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Rapida's `Connect()` — announce what was negotiated, then greet."""
        greeting = (settings.VOICE_GREETING if self.config.greeting is None
                    else self.config.greeting)

        await self._emit(InitializationCompletedPacket(
            stt_provider=self.stt.name, tts_provider=self.tts.name,
            vad_provider=self.vad.name, greeting=greeting))
        # The opening state of the gate, so the officer is told how to be heard
        # before they first speak rather than after being ignored once.
        await self._emit_wake_state(self.state.context_id)

        self._watchdog = asyncio.create_task(self._watch())

        if greeting:
            await self.on_packet(InjectMessagePacket(text=greeting, kind="greeting"))

    async def close(self, reason: str = "closed") -> None:
        if self._closed:
            return
        self._closed = True
        for task in (self._turn, self._watchdog):
            if task is not None and not task.done():
                task.cancel()
        for component in (self.denoiser, self.vad, self.stt, self.tts,
                          self.eos, self.aggregator):
            try:
                await component.close()
            except Exception:
                log.exception("error closing %s", type(component).__name__)
        log.info("voice session closed for %s (%s)", self.user.username, reason)

    async def _watch(self) -> None:
        """Rapida's idle and max-session behaviours.

        A microphone left open is both a privacy problem and a cost problem, so
        a session that stops being used closes itself rather than waiting for
        someone to remember.

        Neither limit announces itself. The assistant is always on and the
        browser reopens the channel immediately, so both of these are internal
        recycling; saying "this session has reached its time limit" out loud
        would be telling an officer about a socket, twice an hour, in the
        middle of their work.
        """
        idle_limit = self.config.idle_timeout or settings.VOICE_IDLE_TIMEOUT
        max_limit = (self.config.max_session_seconds
                     or settings.VOICE_MAX_SESSION_SECONDS)
        try:
            while not self._closed:
                await asyncio.sleep(5)
                if max_limit and self.state.session_seconds() > max_limit:
                    # Never mid-answer: cutting the channel while the officer
                    # is listening loses the second half of a reply.
                    if self.state.output_active:
                        continue
                    await self.close("max_session")
                    return
                if (idle_limit and self.state.state is TurnState.IDLE
                        and self.state.idle_seconds() > idle_limit):
                    await self.close("idle")
                    return
        except asyncio.CancelledError:
            return

    # ── inbound from the client ─────────────────────────────────────────────

    async def push_audio(self, chunk: bytes) -> None:
        """Raw bytes from the websocket → exact 20 ms frames → the pipeline."""
        if self._closed or not chunk:
            return
        pcm = normalise_inbound(chunk, self.config.input_sample_rate)
        for frame in self._frames.push(pcm):
            await self.on_packet(UserAudioReceivedPacket(
                context_id=self.state.context_id or "", audio=frame))

    async def push_text(self, text: str) -> None:
        """A typed question, or a transcript the browser recognised itself."""
        if self._closed or not text.strip():
            return
        await self.on_packet(UserTextReceivedPacket(
            context_id=new_context_id(), text=text))

    def set_playback(self, active: bool) -> None:
        """The client reporting whether its speakers are live.

        Gates the recogniser for the real duration of an answer rather than
        the duration of the *send*, which is what stops the assistant hearing
        itself. See `state.set_client_playback`.
        """
        self.state.set_client_playback(active)

    async def finish_turn(self) -> None:
        """The client released push-to-talk."""
        tail = self._frames.flush()
        if tail:
            await self.on_packet(UserAudioReceivedPacket(
                context_id=self.state.context_id or "", audio=tail))
        await self.stt.flush(self.state.context_id or new_context_id())
        await self.eos.flush(self.state.context_id or new_context_id())

    # ── the central router ──────────────────────────────────────────────────

    async def on_packet(self, *packets: Packet) -> None:
        """Rapida's `OnPacket()`. Every arrow in the module docstring is here."""
        for packet in packets:
            if self._closed:
                return
            try:
                await self._dispatch(packet)
            except Exception as exc:
                log.exception("voice pipeline error handling %s", packet.name)
                await self._emit(PipelineErrorPacket(
                    context_id=packet.context_id,
                    component=packet.name.value, message=str(exc)[:200]))

    async def _dispatch(self, packet: Packet) -> None:
        # ── audio front end ────────────────────────────────────────────────
        if isinstance(packet, UserAudioReceivedPacket):
            await self.denoiser.process(DenoiseAudioPacket(
                context_id=packet.context_id, audio=packet.audio))
            return

        if isinstance(packet, DenoisedAudioPacket):
            await self.vad.process(packet)
            return

        if isinstance(packet, VadSpeechActivityPacket):
            await self._on_speech_activity(packet)
            return

        # ── recognition ────────────────────────────────────────────────────
        if isinstance(packet, SpeechToTextAudioPacket):
            await self.stt.feed(packet)
            return

        if isinstance(packet, SpeechToTextPacket):
            self.telemetry.mark(packet.context_id, "transcript")
            await self._emit(packet)              # live caption
            await self.eos.process(packet)
            return

        if isinstance(packet, InterimEndOfSpeechPacket):
            await self._emit(packet)
            return

        # ── the question ───────────────────────────────────────────────────
        if isinstance(packet, UserTextReceivedPacket):
            await self._begin_turn(packet.context_id, packet.text, spoken=False)
            return

        if isinstance(packet, EndOfSpeechPacket):
            self.telemetry.mark(packet.context_id, "end_of_speech")
            await self._begin_turn(packet.context_id, packet.text)
            return

        # ── the answer ─────────────────────────────────────────────────────
        if isinstance(packet, ExecuteLLMPacket):
            await self._run_assistant(packet)
            return

        if isinstance(packet, (LLMResponseDeltaPacket, LLMResponseDonePacket)):
            if self.state.is_stale(packet.context_id):
                return
            if isinstance(packet, LLMResponseDeltaPacket):
                self.telemetry.mark(packet.context_id, "first_token")
            await self._emit(packet)
            await self.aggregator.aggregate(packet)
            return

        if isinstance(packet, (LLMToolInvokedPacket, LLMNavigatePacket)):
            if not self.state.is_stale(packet.context_id):
                await self._emit(packet)
            return

        # ── synthesis ──────────────────────────────────────────────────────
        if isinstance(packet, TextToSpeechTextPacket):
            await self._speak(packet)
            return

        if isinstance(packet, TextToSpeechAudioPacket):
            if self.state.is_stale(packet.context_id):
                return                            # audio from an abandoned turn
            if packet.audio:
                self.telemetry.mark(packet.context_id, "first_audio")
            await self._emit(packet)
            return

        if isinstance(packet, TextToSpeechDonePacket):
            if not self.state.is_stale(packet.context_id):
                await self._emit(packet)
                self.telemetry.finish(packet.context_id)
                self.state.finish()
                # Sentinel has just stopped talking, so the officer is now
                # mid-conversation: the next question needs no wake word. This
                # is the half of the gate that makes it liveable — "and
                # Rajkot?" is a follow-up, not a new summons.
                self.wake.open_follow_up()
                await self._emit_wake_state(packet.context_id)
                await self._emit(TurnChangePacket(context_id=packet.context_id,
                                                  speaker="user"))
            return

        # ── interruption ───────────────────────────────────────────────────
        if isinstance(packet, InterruptionDetectedPacket):
            await self._interrupt(packet)
            return

        if isinstance(packet, InjectMessagePacket):
            await self._inject(packet)
            return

        await self._emit(packet)

    # ── branches ────────────────────────────────────────────────────────────

    async def _on_speech_activity(self, packet) -> None:
        """The VAD's verdict on one frame — and the barge-in decision."""
        # The denoiser only learns its noise profile during silence.
        if hasattr(self.denoiser, "speech_active"):
            self.denoiser.speech_active = packet.is_speech

        if self.state.observe_speech(packet.is_speech, packet.probability):
            await self.on_packet(InterruptionDetectedPacket(
                context_id=self.state.context_id))
            return

        # Do not feed the recogniser while the assistant is talking, or it
        # transcribes the assistant. The VAD above still saw this frame, which
        # is what makes barge-in possible at all.
        if self.state.suppress_microphone:
            return

        # A streaming recogniser gets every frame, silence included, because it
        # runs its own endpointer and that endpointer is the thing deciding
        # when the turn ended. Feeding it only what the energy VAD calls speech
        # starves it of exactly the silence it is listening for: measured, the
        # turn then never ended on its own and the answer arrived ten seconds
        # after the officer stopped talking.
        #
        # The batch path below is unchanged — it has no endpointer, so for it
        # silence is only a signal to flush.
        if self.stt.is_streaming:
            if self.state.state is TurnState.IDLE and packet.is_speech:
                self.state.begin_turn(new_context_id())
                self.telemetry.begin(self.state.context_id)
                self.telemetry.mark(self.state.context_id, "speech_start")
                await self._emit(TurnChangePacket(
                    context_id=self.state.context_id, speaker="user"))
            await self.on_packet(SpeechToTextAudioPacket(
                context_id=self.state.context_id or new_context_id(),
                audio=packet.audio))
            return

        if not packet.is_speech:
            await self._on_silence()
            return

        self._silence_ms = 0.0
        if self.state.state is TurnState.IDLE:
            self.state.begin_turn(new_context_id())
            self.telemetry.begin(self.state.context_id)
            self.telemetry.mark(self.state.context_id, "speech_start")
            await self._emit(TurnChangePacket(context_id=self.state.context_id,
                                              speaker="user"))

        await self.on_packet(SpeechToTextAudioPacket(
            context_id=self.state.context_id, audio=packet.audio))

    async def _on_silence(self) -> None:
        """A quiet frame — and, for a batch recogniser, the only thing that ever
        ends an utterance.

        A streaming recogniser emits interim transcripts while the officer is
        still talking, and those drive the end-of-speech detector. A batch one
        emits nothing at all until `flush()`, so with nothing watching the
        silence its buffer grows for the whole session and not one word is ever
        transcribed. Whisper — the default here, and the only recogniser that
        handles Gujarati and code-mixed speech well — is batch by construction,
        so this is not an edge case: without this branch the assistant simply
        never answers anything that was spoken.

        Rapida puts the same decision in the same place, and it belongs here
        rather than in the detector because the VAD's verdict is the only
        evidence available before a transcript exists.
        """
        if self.stt.is_streaming or self._flushing:
            return
        if self.state.state is not TurnState.LISTENING:
            return

        self._silence_ms += FRAME_MS
        if self._silence_ms < self._eos_silence_ms:
            return

        context_id = self.state.context_id or new_context_id()
        self._silence_ms = 0.0
        # Transcription is a network round trip and more silence keeps arriving
        # during it. Without this flag every subsequent quiet frame starts
        # another one.
        self._flushing = True
        try:
            self.telemetry.mark(context_id, "end_of_speech")
            await self.stt.flush(context_id)
            # The recogniser has spoken its one and only word on this utterance,
            # so there is nothing left to wait for: release the segment now
            # instead of paying the detector's silence timeout a second time.
            await self.eos.flush(context_id)
        finally:
            self._flushing = False

        # Nothing came back — silence, noise, or a rejected hallucination. The
        # turn never became a question, so it must not be left in LISTENING or
        # the next utterance is appended to this one.
        if self.state.state is TurnState.LISTENING:
            self.state.finish()

    async def _emit_wake_state(self, context_id: str) -> None:
        """Tell the client whether the name is currently needed.

        Control-sized and sent only on transitions, not per frame — this is a
        label under an orb, not something the audio path should carry.
        """
        await self._emit(WakeStatePacket(
            context_id=context_id,
            listening=self.wake.listening,
            required=self.wake.enabled,
            expires_in=round(self.wake.expires_in, 1)))

    async def _begin_turn(self, context_id: str, text: str, *,
                          spoken: bool = True) -> None:
        if not text.strip():
            return

        # Was this said *to* Sentinel? The microphone is open from sign-in, so
        # most speech it hears is two officers talking to each other, and an
        # assistant that answers that out loud is talking over the room. Typed
        # questions pass untouched — clicking into the input box and typing is
        # about as unambiguous as addressing gets.
        was_listening = self.wake.listening
        text = self.wake.admit(text, spoken=spoken)
        if text is None:
            return
        if spoken and not was_listening:
            # The gate just opened. Tell the client, so the hint stops saying
            # "say Sentinel" while the officer is plainly being heard.
            await self._emit_wake_state(context_id)
        if not text.strip():
            # "Sentinel." and nothing else: an address with no question. The
            # window is now open, so the sentence the officer is still forming
            # arrives as a follow-up and needs no name in front of it.
            return

        self.state.begin_thinking(context_id)
        if self.telemetry.get(context_id) is None:
            self.telemetry.begin(context_id)
        trace = self.telemetry.get(context_id)
        if trace is not None:
            trace.transcript_chars = len(text)

        # One turn at a time. A second question while the first is running
        # cancels it — which is what the officer meant by asking again.
        if self._turn is not None and not self._turn.done():
            self._turn.cancel()
        self._turn = asyncio.create_task(
            self.on_packet(ExecuteLLMPacket(context_id=context_id, text=text)))

    async def _run_assistant(self, packet: ExecuteLLMPacket) -> None:
        """Ask the assistant. Identical policy to the typed endpoint.

        The refusal check runs here on the transcript, before the agent sees
        it, so speaking a request for the officer roster is refused exactly as
        typing it is. Voice adds no capability.
        """
        text = guard.normalise(packet.text)[: settings.ASSISTANT_MAX_QUERY_CHARS]
        if not text:
            return

        refusal = guard.refusal_for(text)
        if refusal is not None:
            message, reason = refusal
            log_action(self.db, "assistant_refused", "",
                       {"query": text[:200], "reason": reason, "channel": "voice"})
            await self.on_packet(LLMResponseDonePacket(
                context_id=packet.context_id, text=message, intent="refused",
                source="refusal"))
            return

        ctx = assistant_tools.ToolContext(session=self.db, user=self.user,
                                          page=self.config.page)
        try:
            intent, answer = await agent.answer(text, ctx)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("voice assistant turn failed")
            message = "Something went wrong working that out."
            await self.on_packet(LLMResponseDonePacket(
                context_id=packet.context_id, text=message, intent="error"))
            return

        if self.state.is_stale(packet.context_id):
            return

        trace = self.telemetry.get(packet.context_id)
        if trace is not None:
            trace.tools = [step.get("tool", "") for step in answer.trace]
            trace.reply_chars = len(answer.speech)

        for step in answer.trace:
            await self.on_packet(LLMToolInvokedPacket(
                context_id=packet.context_id, tool=step.get("tool", ""),
                arguments=step.get("arguments", {}),
                display=answer.data.get(step.get("tool", ""), {})))

        if answer.navigate:
            await self.on_packet(LLMNavigatePacket(context_id=packet.context_id,
                                                   path=answer.navigate))

        log_action(self.db, "assistant_query", "",
                   {"query": text[:200], "intent": intent, "channel": "voice",
                    "tools": [s.get("tool") for s in answer.trace][:8],
                    "model": answer.model or ""})

        await self.on_packet(LLMResponseDonePacket(
            context_id=packet.context_id, text=answer.speech, intent=intent,
            source=answer.source if hasattr(answer, "source") else ""))

    async def _speak(self, packet: TextToSpeechTextPacket) -> None:
        """Normalise, then synthesise. The last step before audio."""
        if self.state.is_stale(packet.context_id):
            return
        spoken = self.normalizer.normalize(packet.text)
        if not spoken:
            return

        self.telemetry.mark(packet.context_id, "first_sentence")
        if self.state.state is not TurnState.SPEAKING:
            self.state.begin_speaking(packet.context_id)
            await self._emit(TurnChangePacket(context_id=packet.context_id,
                                              speaker="assistant"))

        # The client needs the text whichever provider is in use — for the
        # transcript panel, and for browser-side synthesis to have something
        # to say.
        await self._emit(TextToSpeechTextPacket(context_id=packet.context_id,
                                                text=spoken))
        self.tts.clear(packet.context_id)
        await self.tts.speak(TextToSpeechTextPacket(
            context_id=packet.context_id, text=spoken))

    async def _interrupt(self, packet: InterruptionDetectedPacket) -> None:
        """Stop everything belonging to the current turn.

        Order matters: mark the context stale *first*, so anything still in
        flight from the LLM or the synthesiser is dropped on arrival rather
        than racing the cancellations below.
        """
        context_id = packet.context_id or self.state.context_id
        self.state.mark_interrupted(context_id)

        trace = self.telemetry.get(context_id)
        if trace is not None:
            trace.interrupted = True

        if self._turn is not None and not self._turn.done():
            self._turn.cancel()
        await self.tts.interrupt(context_id)
        await self.eos.interrupt(context_id)
        # Audio buffered for the abandoned turn must not be prepended to what
        # the officer says next.
        if hasattr(self.stt, "reset"):
            self.stt.reset()
        self._silence_ms = 0.0
        self.aggregator.reset()
        if hasattr(self.vad, "reset"):
            self.vad.reset()

        await self._emit(packet)
        self.state.finish()

    async def _inject(self, packet: InjectMessagePacket) -> None:
        """Say something no question asked for — greeting, live alert, notice."""
        context_id = packet.context_id or new_context_id()
        await self._emit(packet)
        await self.on_packet(TextToSpeechTextPacket(context_id=context_id,
                                                    text=packet.text))
        await self.on_packet(TextToSpeechDonePacket(context_id=context_id,
                                                    text=packet.text))

    # ── diagnostics ─────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "user": self.user.username,
            "providers": {"stt": self.stt.name, "tts": self.tts.name,
                          "vad": self.vad.name, "denoiser": self.denoiser.name,
                          "eos": self.eos.name},
            "state": self.state.snapshot(),
            "telemetry": self.telemetry.averages(),
            "uptime_seconds": round(time.monotonic() - self.state.started_at, 1),
        }
