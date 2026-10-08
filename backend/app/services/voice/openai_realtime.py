"""The second realtime engine: OpenAI's Realtime API over a WebSocket.

A drop-in for `realtime.GeminiLiveSession` — same constructor, same surface
(`connect`, `push_audio`, `push_text`, `set_playback`, `barge_in`,
`finish_turn`, `close`, `snapshot`), same packets out — so the voice router can
try the engines in `VOICE_REALTIME_PROVIDERS` order and fall back from one to
the other without the channel noticing.

Everything that makes the assistant safe is shared, not re-implemented: the
tool list and rank filter (`assistant/tools.py`), the denylist on what the
officer actually said (`guard`), the system prompt with the language and
confirmation rules (`realtime._system_prompt`), and the tool path with its
spoken-yes check and screen effects (`realtime.execute_tool`).

Protocol notes (GA Realtime API):

  * audio is PCM16 mono at 24 kHz both ways; the console runs at 16 kHz, so it
    is resampled at the edge exactly as the Gemini engine does;
  * turn-taking is OpenAI's `semantic_vad`, which, like Gemini, judges the end
    of a turn from the words rather than a silence timer;
  * tool calls are taken from `response.done`, not from
    `response.function_call_arguments.done` — the latter also fires for a
    response that was interrupted or cancelled, and a cancelled call must not
    run;
  * the officer's transcript arrives asynchronously, often after the model has
    started answering. `confirm_action` therefore waits briefly for it, so the
    spoken-yes check reads the officer's words and not an empty string.

An account with no credit opens the socket happily and then fails the first
response with `insufficient_quota`. That is treated as an engine failure — the
engine is parked and the client reconnects onto the next engine — rather than
a silent assistant.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from sqlmodel import Session as DbSession

from app.config import settings
from app.models import User
from app.services.assistant import guard
from app.services.assistant import tools as assistant_tools
from app.services.voice.audio import resample
from app.services.voice.realtime import _system_prompt, execute_tool
from app.services.voice.types import (
    SAMPLE_RATE,
    InitializationCompletedPacket,
    InterruptionDetectedPacket,
    LLMResponseDonePacket,
    PipelineErrorPacket,
    SpeechToTextPacket,
    TextToSpeechAudioPacket,
    TextToSpeechTextPacket,
    TurnChangePacket,
    WakeStatePacket,
    new_context_id,
)

log = logging.getLogger("sentinel.voice.openai_realtime")

URL = "wss://api.openai.com/v1/realtime?model={model}"
OPENAI_RATE = 24_000
CONNECT_TIMEOUT = 15.0
#: How long confirm_action waits for the officer's transcript to land.
TRANSCRIPT_WAIT_SECONDS = 2.5
#: Codes that mean the account, not the request, is the problem.
_ACCOUNT_ERRORS = ("insufficient_quota", "credit_balance", "invalid_api_key",
                   "billing", "account_deactivated")

# Same failure bookkeeping as the Gemini engine, kept separately so one
# provider's outage never parks the other.
_failures = 0
_blocked_until = 0.0


def available() -> bool:
    if not (settings.VOICE_REALTIME_ENABLED and settings.OPENAI_API_KEY):
        return False
    if time.monotonic() < _blocked_until:
        return False
    try:
        import websockets  # noqa: F401
        return True
    except Exception:
        log.warning("OPENAI_API_KEY is set but websockets is missing")
        return False


def note_failure(reason: str, *, account: bool = False) -> None:
    """Count a failure; an account-level one (no credit, bad key) parks the
    engine at once and for longer, since no reconnect will fix it."""
    global _failures, _blocked_until
    _failures += 1
    if account:
        _blocked_until = time.monotonic() + max(settings.VOICE_REALTIME_COOLDOWN_SECONDS, 1800)
        _failures = 0
        log.warning("OpenAI realtime parked (%s)", reason)
    elif _failures >= settings.VOICE_REALTIME_FAILURE_THRESHOLD:
        _blocked_until = time.monotonic() + settings.VOICE_REALTIME_COOLDOWN_SECONDS
        _failures = 0
        log.warning("OpenAI realtime failed repeatedly (%s) — parked %.0fs",
                    reason, settings.VOICE_REALTIME_COOLDOWN_SECONDS)


def note_success() -> None:
    global _failures, _blocked_until
    _failures = 0
    _blocked_until = 0.0


def cooldown_remaining() -> float:
    return max(0.0, _blocked_until - time.monotonic())


def _languages() -> list[str]:
    """VOICE_LANGUAGE_HINTS (BCP-47, e.g. en-IN) as ISO-639-1 codes."""
    codes = [c.strip().split("-")[0].lower()
             for c in settings.VOICE_LANGUAGE_HINTS.split(",") if c.strip()]
    return list(dict.fromkeys(c for c in codes if len(c) == 2))


def _tools(schemas: list[dict]) -> list[dict]:
    out = []
    for schema in schemas:
        fn = schema.get("function") or {}
        out.append({"type": "function", "name": fn.get("name"),
                    "description": (fn.get("description") or "")[:1000],
                    "parameters": fn.get("parameters") or {"type": "object",
                                                           "properties": {}}})
    return out


def session_config(instructions: str, tools: list[dict], *, hints: bool = True) -> dict:
    transcription: dict = {"model": settings.OPENAI_TRANSCRIBE_MODEL}
    if hints and _languages():
        transcription["languages"] = _languages()
    return {
        "type": "realtime",
        "instructions": instructions,
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": OPENAI_RATE},
                "transcription": transcription,
                "turn_detection": {"type": "semantic_vad",
                                   "eagerness": settings.OPENAI_REALTIME_EAGERNESS,
                                   "create_response": True,
                                   "interrupt_response": True},
            },
            "output": {"format": {"type": "audio/pcm", "rate": OPENAI_RATE},
                       "voice": settings.OPENAI_REALTIME_VOICE},
        },
        "tools": _tools(tools),
        "tool_choice": "auto",
    }


class OpenAIRealtimeSession:
    """One officer, one microphone, one OpenAI Realtime socket."""

    _turn_text: str = ""
    _turn_started: float = 0.0
    _turn_refused: bool = False
    _reader: asyncio.Task | None = None

    def __init__(self, *, user: User, db: DbSession, config, emit) -> None:
        self.user = user
        self.db = db
        self.config = config
        self._emit = emit
        self.context_id = new_context_id()
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._closed = False
        self._playing = False
        self._healthy = False
        self._responding = False
        self._transcribed = asyncio.Event()
        self._transcribed.set()
        self._tools = assistant_tools.for_role(user.role)
        self._names = [t.name for t in self._tools]

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def _send(self, event: dict) -> None:
        if self._ws is not None and not self._closed:
            await self._ws.send(json.dumps(event))

    async def _configure(self, *, hints: bool) -> dict:
        """session.update, then wait for the server to accept or refuse it —
        so a bad model name or option fails here, at connect, where the router
        can still fall back, instead of on the officer's first question."""
        await self._send({"type": "session.update", "session": session_config(
            _system_prompt(self.user, self.config.page, self._names),
            [t.schema() for t in self._tools], hints=hints)})
        deadline = time.monotonic() + CONNECT_TIMEOUT
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(self._ws.recv(), CONNECT_TIMEOUT)
            event = json.loads(raw)
            if event.get("type") == "session.updated":
                return event
            if event.get("type") == "error":
                return event
        raise TimeoutError("no session.updated from OpenAI")

    async def connect(self) -> None:
        import websockets

        try:
            self._ws = await asyncio.wait_for(websockets.connect(
                URL.format(model=settings.OPENAI_REALTIME_MODEL),
                additional_headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                max_size=None,
                # api.openai.com resolves to two addresses and one of them is
                # unreachable from some networks (this one included); racing
                # them is what keeps the handshake from hanging.
                happy_eyeballs_delay=0.25), CONNECT_TIMEOUT)
            reply = await self._configure(hints=True)
            if reply.get("type") == "error" and any(
                    code in json.dumps(reply.get("error")) for code in _ACCOUNT_ERRORS):
                raise RuntimeError(str(reply.get("error"))[:300])
            if reply.get("type") == "error":
                # Language hints are the newest option here; a model that
                # refuses them must cost the hints, not the microphone.
                log.warning("openai realtime: session.update refused (%s) — "
                            "retrying without language hints",
                            (reply.get("error") or {}).get("message"))
                reply = await self._configure(hints=False)
                if reply.get("type") == "error":
                    raise RuntimeError(str(reply.get("error"))[:300])
        except Exception as exc:
            text = str(exc)
            note_failure(f"connect: {type(exc).__name__}",
                         account=any(code in text for code in _ACCOUNT_ERRORS))
            await self._close_socket()
            raise

        self._reader = asyncio.create_task(self._read())
        log.info("openai realtime session open user=%s model=%s tools=%d",
                 self.user.username, settings.OPENAI_REALTIME_MODEL, len(self._tools))
        await self._emit(InitializationCompletedPacket(
            context_id=self.context_id, stt_provider="openai_realtime",
            tts_provider="openai_realtime", vad_provider="openai_realtime",
            greeting=""))
        await self._emit(WakeStatePacket(context_id=self.context_id, listening=True,
                                         required=False, expires_in=0.0))
        if self.config.greeting:
            await self.push_text(self.config.greeting, as_prompt=True)

    async def _close_socket(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None

    async def close(self, reason: str = "closed") -> None:
        if self._closed:
            return
        self._closed = True
        if self._reader is not None:
            self._reader.cancel()
        await self._close_socket()
        log.info("openai realtime session closed (%s) user=%s", reason, self.user.username)

    # ── from the client ─────────────────────────────────────────────────────

    async def push_audio(self, chunk: bytes) -> None:
        if self._ws is None or self._closed:
            return
        try:
            pcm = resample(chunk, self.config.input_sample_rate, OPENAI_RATE)
            await self._send({"type": "input_audio_buffer.append",
                              "audio": base64.b64encode(pcm).decode("ascii")})
        except Exception as exc:
            log.warning("openai realtime: audio send failed (%s)", exc)

    async def push_text(self, text: str, *, as_prompt: bool = False) -> None:
        if self._ws is None or self._closed or not text.strip():
            return
        if not as_prompt:
            refusal = guard.refusal_for(guard.normalise(text))
            if refusal is not None:
                await self._say_locally(refusal[0])
                return
            self._turn_text = text[:2000]
            self._turn_started = time.monotonic()
        try:
            await self._send({"type": "conversation.item.create", "item": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": text[:2000]}]}})
            await self._send({"type": "response.create"})
        except Exception as exc:
            log.warning("openai realtime: text send failed (%s)", exc)

    def set_playback(self, active: bool) -> None:
        self._playing = active

    async def barge_in(self) -> None:
        if self._responding:
            try:
                await self._send({"type": "response.cancel"})
            except Exception:
                pass
        await self._emit(InterruptionDetectedPacket(context_id=self.context_id,
                                                    reason="client"))

    async def finish_turn(self) -> None:
        """semantic_vad decides when the officer has finished; nothing to do."""
        return None

    # ── from OpenAI ─────────────────────────────────────────────────────────

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    await self._on_event(json.loads(raw))
                except Exception:
                    log.exception("openai realtime: event handling failed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("openai realtime: stream ended (%s)", exc)
        if not self._closed:
            if not self._healthy:
                note_failure("stream died unused")
            await self._emit(PipelineErrorPacket(
                context_id=self.context_id,
                message="The voice link dropped. Reconnecting."))

    def _mark_healthy(self) -> None:
        if not self._healthy:
            self._healthy = True
            note_success()

    async def _on_event(self, event: dict) -> None:
        kind = event.get("type", "")

        if kind in ("response.output_audio.delta", "response.audio.delta"):
            self._mark_healthy()
            pcm = base64.b64decode(event.get("delta") or "")
            if pcm:
                await self._emit(TextToSpeechAudioPacket(
                    context_id=self.context_id,
                    audio=resample(pcm, OPENAI_RATE, SAMPLE_RATE)))
            return

        if kind in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
            text = event.get("transcript") or ""
            if text:
                await self._emit(TextToSpeechTextPacket(context_id=self.context_id, text=text))
            return

        if kind == "input_audio_buffer.speech_started":
            if not self._turn_text:
                self._turn_started = time.monotonic()
                self._turn_refused = False
            self._transcribed.clear()
            if self._responding or self._playing:
                # The server cancels its own response (interrupt_response); the
                # browser has to stop what it is already playing.
                await self._emit(InterruptionDetectedPacket(
                    context_id=self.context_id, reason="model"))
            return

        if kind == "conversation.item.input_audio_transcription.completed":
            self._mark_healthy()
            text = (event.get("transcript") or "").strip()
            self._transcribed.set()
            if not text:
                return
            await self._emit(SpeechToTextPacket(
                context_id=self.context_id, text=text, is_final=True,
                confidence=0.0, language=self.config.language))
            self._turn_text = f"{self._turn_text} {text}".strip()[-2000:]
            refusal = (None if self._turn_refused
                       else guard.refusal_for(guard.normalise(self._turn_text)))
            if refusal is not None:
                self._turn_refused = True
                log.info("openai realtime: refused (%s) for %s", refusal[1],
                         self.user.username)
                if self._responding:
                    await self._send({"type": "response.cancel"})
                await self._emit(InterruptionDetectedPacket(
                    context_id=self.context_id, reason="refusal"))
                await self._say_locally(refusal[0])
            return

        if kind == "conversation.item.input_audio_transcription.failed":
            self._transcribed.set()
            return

        if kind == "response.created":
            self._responding = True
            return

        if kind == "response.done":
            self._responding = False
            await self._on_response_done(event.get("response") or {})
            return

        if kind == "error":
            error = event.get("error") or {}
            text = f"{error.get('code')} {error.get('type')} {error.get('message')}"
            if error.get("code") == "response_cancel_not_active":
                return
            log.warning("openai realtime error: %s", text[:300])
            if any(code in text for code in _ACCOUNT_ERRORS):
                note_failure(text[:120], account=True)
                await self._emit(PipelineErrorPacket(
                    context_id=self.context_id,
                    message="The OpenAI voice engine is unavailable. Reconnecting."))
                await self.close("account_error")

    async def _on_response_done(self, response: dict) -> None:
        status = response.get("status")
        if status == "failed":
            error = ((response.get("status_details") or {}).get("error") or {})
            text = f"{error.get('code')} {error.get('type')} {error.get('message')}"
            log.warning("openai realtime response failed: %s", text[:300])
            if any(code in text for code in _ACCOUNT_ERRORS):
                note_failure(text[:120], account=True)
                await self._emit(PipelineErrorPacket(
                    context_id=self.context_id,
                    message="The OpenAI voice engine is unavailable. Reconnecting."))
                await self.close("account_error")
                return
        if status != "completed":
            return          # cancelled / incomplete: nothing in it may run

        calls = [item for item in response.get("output") or []
                 if item.get("type") == "function_call"]
        if calls:
            for call in calls:
                name = call.get("name") or ""
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "confirm_action" and not self._transcribed.is_set():
                    try:
                        await asyncio.wait_for(self._transcribed.wait(),
                                               TRANSCRIPT_WAIT_SECONDS)
                    except asyncio.TimeoutError:
                        pass
                payload = await execute_tool(self, name, args if isinstance(args, dict) else {})
                await self._send({"type": "conversation.item.create", "item": {
                    "type": "function_call_output", "call_id": call.get("call_id"),
                    "output": json.dumps(payload, ensure_ascii=False, default=str)}})
            await self._send({"type": "response.create"})
            return

        # A spoken answer finished: the turn is over.
        self._turn_text = ""
        await self._emit(TextToSpeechAudioPacket(context_id=self.context_id,
                                                 audio=b"", is_final=True))
        await self._emit(LLMResponseDonePacket(context_id=self.context_id, text="",
                                               source="openai_realtime"))
        await self._emit(TurnChangePacket(context_id=self.context_id, speaker="user"))

    # ── helpers ─────────────────────────────────────────────────────────────

    async def _say_locally(self, text: str) -> None:
        await self._emit(TextToSpeechTextPacket(context_id=self.context_id, text=text))
        await self._emit(TextToSpeechAudioPacket(context_id=self.context_id,
                                                 audio=b"", is_final=True))
        await self._emit(LLMResponseDonePacket(context_id=self.context_id, text=text,
                                               source="sentinel-guard"))

    def snapshot(self) -> dict:
        return {"engine": "openai_realtime", "model": settings.OPENAI_REALTIME_MODEL,
                "context_id": self.context_id, "speakers_live": self._playing,
                "tools": len(self._tools)}
