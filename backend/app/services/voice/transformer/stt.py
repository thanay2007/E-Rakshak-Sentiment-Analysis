"""Speech-to-text providers.

Four adapters, chosen to cover the range this deployment actually faces rather
than to be a long list:

  **GroqWhisper** — the default when a key exists, which it already does for
  the rest of the product. Whisper large-v3 at Groq's speed, and it handles
  Gujarati, Hindi and code-mixed speech far better than any browser recogniser.
  Batch only.

  **DeepgramStreamingSTT** — the default whenever DEEPGRAM_API_KEY is set, and
  the only adapter here that is not batch. It transcribes while the officer is
  still speaking and does its own endpointing, which is what makes the
  assistant feel conversational rather than walkie-talkie. See the class for
  why that difference is most of the perceived latency.

  **Sarvam** — an Indian provider whose models are trained on Indian languages
  and accents specifically. Where Whisper transcribes Gujarati well but
  Gujarati-accented English indifferently, Sarvam does both. Optional.

  **BrowserSTT** — not a provider at all. It declares that recognition already
  happened in the browser and text will arrive over the websocket. It exists so
  that "no API key configured" degrades to the Web Speech API rather than to a
  microphone that does nothing.

Language handling is one decision worth stating. `auto` is the default and the
language is *not* pinned, because pinning to `en` makes Whisper transliterate
Gujarati into nonsense English rather than transcribing it, and pinning to `gu`
makes it do the reverse to English speech. In a control room where officers
switch language mid-sentence, letting the model decide per utterance is the
only setting that works.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from app.config import settings
from app.services.voice.audio import to_wav
from app.services.voice.transformer.base import SpeechToText
from app.services.voice.types import (SAMPLE_RATE, OnPacket,
                                      SpeechToTextAudioPacket,
                                      SpeechToTextPacket)

log = logging.getLogger("sentinel.voice.stt")

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

#: What the officer is likely to be saying, given to Whisper as a prior.
#:
#: This is the cheapest accuracy the pipeline can buy. Whisper decodes toward
#: whatever it finds plausible, and the vocabulary of this console is not what
#: it finds plausible by default: "threat score" comes back as "thread score",
#: "brief me" as "read me", "Vadodara" as almost anything. Every one of those
#: is a question the assistant then answers wrongly or not at all.
#:
#: It is a prior and not an instruction — Whisper cannot be made to emit
#: arbitrary text by putting it here, so this cannot become an injection route.
#: Kept to well under the 224-token window it is truncated to.
WHISPER_PROMPT = (
    "Gujarat Police SENTINEL monitoring console. Cities: Surat, Ahmedabad, "
    "Vadodara, Rajkot. Terms: threat score, threat feed, brief me, situation "
    "brief, critical alerts, watchlist, sentiment, hashtags, coordination, "
    "escalation, misinformation, incitement, inflammatory, fake news, "
    "verified, platform, dashboard, last six hours, last twenty-four hours."
)
SARVAM_TRANSCRIBE_URL = "https://api.sarvam.ai/speech-to-text"
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_STREAM_URL = "wss://api.deepgram.com/v1/listen"

#: Words this console uses that a general recogniser mishears. Kept short —
#: keyterm boosting trades general accuracy for these, so it is for nouns the
#: assistant actually branches on (cities it filters by, pages it opens),
#: not for every bit of jargon.
DEEPGRAM_KEYTERMS = (
    "Surat", "Ahmedabad", "Vadodara", "Rajkot", "Gujarat", "Gandhinagar",
    "Sentinel", "watchlist", "concern score", "sentiment", "escalation",
)


class BrowserSTT(SpeechToText):
    """Recognition happens in the browser; nothing to do here.

    Audio frames still flow to the server because the VAD and the interruption
    detector need them — the browser's recogniser gives no usable signal for
    barge-in. Only the transcription step is skipped.
    """

    name = "browser"
    is_streaming = True

    async def feed(self, packet) -> None:
        return None

    async def flush(self, context_id: str) -> None:
        return None

    async def transcribe(self, audio: bytes) -> tuple[str, float, str]:
        return "", 0.0, self.language


class GroqWhisper(SpeechToText):
    """Whisper large-v3 via Groq."""

    name = "groq_whisper"
    is_streaming = False
    hallucinates_on_silence = True

    def __init__(self, on_packet: OnPacket, *, language: str = "auto",
                 model: str = "") -> None:
        super().__init__(on_packet, language=language)
        self.model = model or settings.VOICE_STT_MODEL

    @staticmethod
    def available() -> bool:
        return bool(settings.GROQ_API_KEY)

    async def transcribe(self, audio: bytes) -> tuple[str, float, str]:
        files = {"file": ("utterance.wav", to_wav(audio), "audio/wav")}
        data: dict[str, str] = {"model": self.model,
                                "response_format": "verbose_json",
                                "prompt": WHISPER_PROMPT}
        if self.language and self.language != "auto":
            data["language"] = self.language.split("-")[0]

        async with httpx.AsyncClient(timeout=settings.VOICE_STT_TIMEOUT) as client:
            response = await client.post(
                GROQ_TRANSCRIBE_URL, files=files, data=data,
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"})
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

        payload = response.json()
        raw_text = (payload.get("text") or "").strip()
        segments = payload.get("segments") or []
        # `no_speech_prob` indicates low speech confidence, but don't reject non-empty valid words.
        if segments and not raw_text:
            quiet = sum(1 for s in segments if s.get("no_speech_prob", 0) > 0.85)
            if quiet == len(segments):
                return "", 0.0, payload.get("language", "")
        return (raw_text, 0.9, payload.get("language", ""))


class SarvamSTT(SpeechToText):
    """Sarvam AI — Indian-language models."""

    name = "sarvam"
    is_streaming = False

    def __init__(self, on_packet: OnPacket, *, language: str = "auto",
                 model: str = "saarika:v2") -> None:
        super().__init__(on_packet, language=language)
        self.model = model

    @staticmethod
    def available() -> bool:
        return bool(settings.SARVAM_API_KEY)

    async def transcribe(self, audio: bytes) -> tuple[str, float, str]:
        files = {"file": ("utterance.wav", to_wav(audio), "audio/wav")}
        data = {"model": self.model,
                "language_code": "unknown" if self.language in ("", "auto")
                else self.language}
        async with httpx.AsyncClient(timeout=settings.VOICE_STT_TIMEOUT) as client:
            response = await client.post(
                SARVAM_TRANSCRIBE_URL, files=files, data=data,
                headers={"api-subscription-key": settings.SARVAM_API_KEY})
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        return (payload.get("transcript", ""), 0.9,
                payload.get("language_code", ""))


class DeepgramSTT(SpeechToText):
    """Deepgram Nova — the lowest-latency batch option."""

    name = "deepgram"
    is_streaming = False

    def __init__(self, on_packet: OnPacket, *, language: str = "en-IN",
                 model: str = "nova-2") -> None:
        super().__init__(on_packet, language=language)
        self.model = model

    @staticmethod
    def available() -> bool:
        return bool(settings.DEEPGRAM_API_KEY)

    async def transcribe(self, audio: bytes) -> tuple[str, float, str]:
        params = {"model": self.model, "punctuate": "true", "smart_format": "true"}
        if self.language and self.language != "auto":
            params["language"] = self.language
        async with httpx.AsyncClient(timeout=settings.VOICE_STT_TIMEOUT) as client:
            response = await client.post(
                DEEPGRAM_URL, params=params, content=to_wav(audio),
                headers={"Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                         "Content-Type": "audio/wav"})
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        alternatives = (response.json().get("results", {})
                        .get("channels", [{}])[0].get("alternatives", [{}]))
        best = alternatives[0] if alternatives else {}
        return (best.get("transcript", ""), best.get("confidence", 0.0),
                self.language)


class DeepgramStreamingSTT(SpeechToText):
    """Deepgram over its live WebSocket — the one adapter that is not batch.

    This is where conversational latency actually comes from, and why it is the
    default whenever a key exists.

    A batch recogniser cannot start until the officer has stopped talking. The
    session waits out VOICE_EOS_SILENCE_SECONDS, uploads the whole utterance,
    and waits for a transcript — so the clock only *starts* at the end of the
    sentence, and a 5-second question costs its own length again before the
    assistant has read a single word. Streaming inverts that: audio is
    transcribed while it is still being spoken, and the final transcript lands
    tens of milliseconds after the last word rather than a round trip after it.

    Two things follow from that, both of which the session already knows how to
    use:

    * **Interims.** `is_streaming` is True, so the session shows a live caption
      and the end-of-speech detector sees words while the officer is still
      talking instead of guessing from energy alone.
    * **Endpointing.** Deepgram decides when an utterance ended, from the audio
      and the language model together. That is a far better judge than the
      energy VAD, which cannot tell a thinking pause from a finished sentence
      and is the reason the assistant used to answer half a question.

    The socket is opened lazily on the first frame and torn down with the
    session. If it cannot be opened at all the factory has already fallen back
    to a batch provider, so a Deepgram outage costs latency, never the feature.
    """

    name = "deepgram_streaming"
    is_streaming = True

    def __init__(self, on_packet: OnPacket, *, language: str = "en-IN",
                 model: str = "") -> None:
        super().__init__(on_packet, language=language)
        self.model = model or settings.DEEPGRAM_STREAM_MODEL
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._context_id = ""
        self._lock = asyncio.Lock()
        self._failed = False
        #: Segments Deepgram has marked `is_final` — stable text it will not
        #: revise. Held rather than emitted one by one because a turn is
        #: usually several of them, and the assistant must be asked the whole
        #: question rather than each clause as it lands.
        self._settled: list[str] = []

    @staticmethod
    def available() -> bool:
        if not settings.DEEPGRAM_API_KEY:
            return False
        try:
            import websockets  # noqa: F401
            return True
        except Exception:
            log.warning("DEEPGRAM_API_KEY is set but the `websockets` package "
                        "is missing — streaming STT unavailable")
            return False

    def _url(self) -> str:
        from urllib.parse import urlencode

        params = {
            "model": self.model,
            "encoding": "linear16",
            "sample_rate": str(SAMPLE_RATE),
            "channels": "1",
            "punctuate": "true",
            "smart_format": "true",
            # Interim results are the live caption. Without them this is a
            # slower batch recogniser with extra steps.
            "interim_results": "true",
            # Deepgram's own end-of-utterance judgement, in milliseconds. Kept
            # close to the session's silence window so the two agree about when
            # a turn ended rather than racing.
            "endpointing": str(int(settings.VOICE_EOS_SILENCE_SECONDS * 1000)),
            # A second, independent end-of-turn signal. `speech_final` only
            # arrives if Deepgram hears enough silence *after* the speech, and
            # this client is half-duplex — it stops sending the moment the
            # assistant starts talking — so there are turns where that silence
            # is never transmitted and `speech_final` never comes. UtteranceEnd
            # is derived from word timings instead and still fires.
            "utterance_end_ms": str(max(1000,
                                        int(settings.VOICE_EOS_SILENCE_SECONDS * 1000))),
            # Required for UtteranceEnd to be sent at all.
            "vad_events": "true",
        }
        # Domain vocabulary, boosted. The same accuracy-for-free trick as
        # WHISPER_PROMPT above and needed for the same reason: the recogniser
        # decodes toward what it finds plausible, and this console's nouns are
        # not plausible to a model trained on the open web. Measured on a live
        # round trip, "Surat" came back as "Sirat" without this — and a city
        # name is precisely the word the assistant filters on, so getting it
        # wrong does not degrade the answer, it changes which city was asked
        # about.
        # nova-3 only; older models reject the parameter outright.
        if self.model.startswith("nova-3"):
            params["keyterm"] = list(DEEPGRAM_KEYTERMS)
        # `multi` lets one utterance switch script mid-sentence, which is the
        # normal case here — an officer says a Gujarati place name inside an
        # English question. Pinning a single language is what makes a
        # recogniser transliterate one of them into nonsense.
        if self.language and self.language not in ("", "auto"):
            params["language"] = self.language
        else:
            params["language"] = settings.DEEPGRAM_STREAM_LANGUAGE
        # doseq, because `keyterm` is repeated rather than comma-joined.
        return f"{DEEPGRAM_STREAM_URL}?{urlencode(params, doseq=True)}"

    async def _connect(self):
        if self._ws is not None or self._failed:
            return self._ws
        async with self._lock:
            if self._ws is not None or self._failed:
                return self._ws
            try:
                import websockets

                self._ws = await websockets.connect(
                    self._url(),
                    additional_headers={
                        "Authorization": f"Token {settings.DEEPGRAM_API_KEY}"},
                    open_timeout=settings.VOICE_STT_TIMEOUT,
                    # Deepgram sends its own keepalives; ours would race them.
                    ping_interval=None,
                )
                self._reader = asyncio.create_task(self._read())
                log.info("deepgram: live socket open (%s)", self.model)
            except Exception as exc:
                # Latched: a key Deepgram has refused will not start working
                # because the next frame asked again, and retrying per 20 ms
                # frame would open a socket fifty times a second.
                self._failed = True
                log.warning("deepgram: could not open live socket (%s) — "
                            "this session has no streaming STT", exc)
        return self._ws

    async def _read(self) -> None:
        """One task draining Deepgram's JSON, for the life of the socket.

        Deepgram's three signals mean three different things, and conflating
        them is how a turn ends in the wrong place:

          `is_final`      this *segment* will not be revised. A turn is often
                          several of these, so it is text to keep, not a cue
                          to answer.
          `speech_final`  the endpointer heard silence after the speech: the
                          turn is over. The best signal, when it arrives.
          `UtteranceEnd`  derived from word timings, and the fallback for when
                          the client stopped sending before that silence.

        Whichever end signal lands first releases the settled text and the
        other is then a no-op, because `_finish` clears the buffer.
        """
        try:
            async for raw in self._ws:
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    continue

                kind = payload.get("type")
                if kind == "UtteranceEnd":
                    await self._finish()
                    continue
                if kind not in (None, "Results"):
                    continue

                alternatives = (payload.get("channel", {})
                                .get("alternatives") or [{}])
                text = (alternatives[0].get("transcript") or "").strip()
                confidence = float(alternatives[0].get("confidence") or 0.0)

                if payload.get("is_final"):
                    if text:
                        self._settled.append(text)
                    if payload.get("speech_final"):
                        await self._finish(confidence)
                elif text:
                    # An interim: the live caption, and what the end-of-speech
                    # detector watches. Never a turn boundary.
                    await self._on_packet(SpeechToTextPacket(
                        context_id=self._context_id, text=text, is_final=False,
                        confidence=confidence, language=self.language))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("deepgram: live socket closed (%s)", exc)

    async def _finish(self, confidence: float = 0.0) -> None:
        """Release the settled text as one finished question."""
        text = " ".join(self._settled).strip()
        self._settled.clear()
        if not text:
            return
        await self._on_packet(SpeechToTextPacket(
            context_id=self._context_id, text=text, is_final=True,
            confidence=confidence, language=self.language))

    async def feed(self, packet: SpeechToTextAudioPacket) -> None:
        self._context_id = packet.context_id
        ws = await self._connect()
        if ws is None:
            return
        try:
            await ws.send(packet.audio)
        except Exception as exc:
            log.warning("deepgram: send failed (%s)", exc)
            self._failed = True

    async def flush(self, context_id: str) -> None:
        """Close the turn with whatever Deepgram has settled so far.

        Not the batch behaviour — there is no buffer to transcribe, and
        re-sending the audio would produce a duplicate answer. This is the last
        of the three end-of-turn signals: the caller's own silence detector,
        used when neither `speech_final` nor `UtteranceEnd` arrived. Harmless
        when they did, because `_finish` has already emptied the buffer.
        """
        self._context_id = context_id or self._context_id
        await self._finish()

    async def transcribe(self, audio: bytes) -> tuple[str, float, str]:
        # Required by the interface; unreachable, because feed() never buffers.
        return "", 0.0, self.language

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        if self._ws is not None:
            try:
                # Tells Deepgram to finalise rather than drop the tail.
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        await super().close()


_PROVIDERS: dict[str, type[SpeechToText]] = {
    "browser": BrowserSTT,
    "groq_whisper": GroqWhisper,
    "sarvam": SarvamSTT,
    "deepgram": DeepgramSTT,
    "deepgram_streaming": DeepgramStreamingSTT,
}

#: Tried in order when the configured provider is unavailable. Streaming first
#: — it is the difference between an assistant that replies while you are
#: drawing breath and one that replies a second after you finish. Browser is
#: last and always works, so this never returns nothing.
#:
#: There is no local recogniser any more: this runs as a hosted service, where
#: an in-process Whisper would mean GPU-less CPU inference on the web host,
#: inside the one latency budget in the product that a human is waiting on.
_FALLBACK_ORDER = ("deepgram_streaming", "groq_whisper", "sarvam", "deepgram",
                   "browser")


def create(on_packet: OnPacket, provider: str = "", **kwargs) -> SpeechToText:
    """Factory mirroring Rapida's `transformer.NewSpeechToText`.

    An unavailable provider walks the fallback order rather than failing.
    Getting a working microphone with a less accurate recogniser beats a
    correct error message about a missing key.
    """
    requested = provider or settings.VOICE_STT_PROVIDER
    if requested == "auto":
        # No preference expressed — walk the order, which already puts the
        # streaming recogniser first and degrades to the browser's own.
        candidates = list(_FALLBACK_ORDER)
    else:
        candidates = [requested] + [p for p in _FALLBACK_ORDER if p != requested]

    for name in candidates:
        factory = _PROVIDERS.get(name)
        if factory is None:
            continue
        checker = getattr(factory, "available", None)
        if checker is not None and not checker():
            continue
        if name != requested and requested != "auto":
            log.warning("stt provider %r unavailable — using %r", requested, name)
        elif requested == "auto":
            log.info("stt provider: %s%s", name,
                     "" if factory.is_streaming else " (batch — expect a pause "
                     "after the officer stops speaking; set DEEPGRAM_API_KEY "
                     "for streaming)")
        return factory(on_packet, **kwargs)

    return BrowserSTT(on_packet, **kwargs)


def status() -> list[dict]:
    """Which recognisers this instance could use — for the settings page."""
    return [{"name": name,
             "available": not hasattr(factory, "available") or factory.available(),
             "streaming": factory.is_streaming}
            for name, factory in _PROVIDERS.items()]
