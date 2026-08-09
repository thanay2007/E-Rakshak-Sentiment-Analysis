"""Speech-to-text providers.

Four adapters, chosen to cover the range this deployment actually faces rather
than to be a long list:

  **GroqWhisper** — the default when a key exists, which it already does for
  the rest of the product. Whisper large-v3 at Groq's speed, and it handles
  Gujarati, Hindi and code-mixed speech far better than any browser recogniser.
  Batch only.

  **LocalWhisper** — `openai-whisper` is already a declared dependency of this
  project (the OSINT audio analysis uses it). No key, no network, and on a
  machine with the CUDA build already installed it is fast enough. This is the
  adapter that matters for an air-gapped deployment, which a police
  installation may well become.

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
import logging

import httpx

from app.config import settings
from app.services.voice.audio import to_wav
from app.services.voice.transformer.base import SpeechToText
from app.services.voice.types import OnPacket

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


class LocalWhisper(SpeechToText):
    """Whisper running in-process. No key, no network."""

    name = "local_whisper"
    is_streaming = False
    hallucinates_on_silence = True

    _model = None
    _lock = asyncio.Lock()

    def __init__(self, on_packet: OnPacket, *, language: str = "auto",
                 model: str = "base") -> None:
        super().__init__(on_packet, language=language)
        self.model_size = model or settings.VOICE_STT_LOCAL_MODEL

    @staticmethod
    def available() -> bool:
        try:
            import whisper  # noqa: F401
            return True
        except Exception:
            return False

    async def _load(self):
        if LocalWhisper._model is not None:
            return LocalWhisper._model
        async with LocalWhisper._lock:
            if LocalWhisper._model is None:
                import whisper

                from app.ml.device import resolve_device

                device = resolve_device()
                log.info("loading local whisper %r on %s", self.model_size, device)
                LocalWhisper._model = await asyncio.to_thread(
                    whisper.load_model, self.model_size, device=device)
        return LocalWhisper._model

    async def transcribe(self, audio: bytes) -> tuple[str, float, str]:
        import numpy as np

        model = await self._load()
        samples = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
        options: dict = {"fp16": False, "task": "transcribe"}
        if self.language and self.language != "auto":
            options["language"] = self.language.split("-")[0]

        # Whisper is CPU/GPU-bound and fully synchronous. Off the event loop it
        # goes, or one transcription stalls every other websocket on the server.
        result = await asyncio.to_thread(model.transcribe, samples, **options)
        return (result.get("text", ""), 0.85, result.get("language", ""))


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


_PROVIDERS: dict[str, type[SpeechToText]] = {
    "browser": BrowserSTT,
    "groq_whisper": GroqWhisper,
    "local_whisper": LocalWhisper,
    "sarvam": SarvamSTT,
    "deepgram": DeepgramSTT,
}

#: Tried in order when the configured provider is unavailable. Browser is last
#: and always works, so this never returns nothing.
_FALLBACK_ORDER = ("groq_whisper", "sarvam", "deepgram", "local_whisper", "browser")


def create(on_packet: OnPacket, provider: str = "", **kwargs) -> SpeechToText:
    """Factory mirroring Rapida's `transformer.NewSpeechToText`.

    An unavailable provider walks the fallback order rather than failing.
    Getting a working microphone with a less accurate recogniser beats a
    correct error message about a missing key.
    """
    requested = provider or settings.VOICE_STT_PROVIDER
    candidates = [requested] + [p for p in _FALLBACK_ORDER if p != requested]

    for name in candidates:
        factory = _PROVIDERS.get(name)
        if factory is None:
            continue
        checker = getattr(factory, "available", None)
        if checker is not None and not checker():
            continue
        if name != requested:
            log.warning("stt provider %r unavailable — using %r", requested, name)
        return factory(on_packet, **kwargs)

    return BrowserSTT(on_packet, **kwargs)


def status() -> list[dict]:
    """Which recognisers this instance could use — for the settings page."""
    return [{"name": name,
             "available": not hasattr(factory, "available") or factory.available(),
             "streaming": factory.is_streaming}
            for name, factory in _PROVIDERS.items()]
