"""Text-to-speech providers.

The default is `auto`: take the best voice this deployment actually has keys
for, and fall back rather than fail. In order of quality:

  **ElevenLabsTTS** — the best available, streamed so playback starts before
  synthesis finishes. The default voice is female and deliberately a calm,
  level one; an assistant that reads a threat score with enthusiasm is worse
  than one that reads it flatly.

  **SarvamTTS** — Indian-language voices. The one that pronounces "Vadodara"
  and "Rajkot" correctly, which every en-US voice gets wrong.

  **BrowserTTS** — emits the text with a flag and the browser speaks it. No
  key, no cost, no round trip, and the answer never leaves the machine, which
  in a police deployment is a real argument and not only a fallback. On
  Windows/Edge the voices it reaches are Microsoft's neural ones — the same
  engine a paid API would sell — so this is a good deal more than a stub. What
  it gives up is consistency: what an officer hears depends on their browser.

There is no local synthesiser. Kokoro (onnxruntime) and Piper (over HTTP) used
to sit between Sarvam and the browser; on a hosted deployment they are 310 MB
of weights and blocking CPU synthesis on the web host, competing with the API
and with every other officer's audio, to produce a voice the browser already
makes for free with no round trip at all.

Groq's PlayAI voices used to be here and were the obvious choice, since the
product already holds a Groq key. They are gone: `playai-tts` now answers
`model_decommissioned`, and leaving it in the chain bought a wasted round trip
and a confusing status line before every fallback.

Streaming matters more than it looks. `speak()` may emit many audio packets for
one sentence, and each is playable on arrival, so the officer hears the first
syllable while the rest is still being generated. Combined with the sentence
aggregator upstream, the effect is that speech begins about a second after the
question and never pauses again.

Every adapter checks `cancelled()` between chunks. That is what makes barge-in
feel instant: the moment the officer talks over an answer, the next chunk is
dropped rather than the session waiting for a provider to acknowledge a cancel
it may never acknowledge.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.voice.audio import from_wav, resample
from app.services.voice.transformer.base import TextToSpeech
from app.services.voice.types import (SAMPLE_RATE, OnPacket, TextToSpeechAudioPacket,
                                      TextToSpeechTextPacket)

log = logging.getLogger("sentinel.voice.tts")

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"


class BrowserTTS(TextToSpeech):
    """The browser speaks it. No audio crosses the network."""

    name = "browser"
    is_client_side = True

    async def speak(self, packet: TextToSpeechTextPacket) -> None:
        if self.cancelled(packet.context_id):
            return
        # An empty audio packet carrying is_final is the signal the channel
        # turns into a "speak this yourself" instruction for the client. The
        # text has already travelled in the TextToSpeechTextPacket.
        await self._on_packet(TextToSpeechAudioPacket(
            context_id=packet.context_id, audio=b"", is_final=True))


class SarvamTTS(TextToSpeech):
    """Sarvam AI — Indian-language voices."""

    name = "sarvam"
    #: A bulbul:v2 speaker. The v1 names (meera, pavithra, …) are rejected
    #: outright by v2, so the default has to move with the model.
    DEFAULT_VOICE = "anushka"

    def __init__(self, on_packet: OnPacket, *, voice: str = "",
                 language: str = "en-IN") -> None:
        super().__init__(on_packet, voice=voice or self.DEFAULT_VOICE,
                         language=language)

    @staticmethod
    def available() -> bool:
        return bool(settings.SARVAM_API_KEY)

    async def speak(self, packet: TextToSpeechTextPacket) -> None:
        if self.cancelled(packet.context_id) or not packet.text.strip():
            return
        body = {"inputs": [packet.text[:1500]],
                "target_language_code": self.language,
                "speaker": self.voice, "speech_sample_rate": SAMPLE_RATE,
                "model": "bulbul:v2"}
        async with httpx.AsyncClient(timeout=settings.VOICE_TTS_TIMEOUT) as client:
            response = await client.post(
                SARVAM_TTS_URL, json=body,
                headers={"api-subscription-key": settings.SARVAM_API_KEY})
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        if self.cancelled(packet.context_id):
            return

        import base64

        for encoded in response.json().get("audios", []):
            if self.cancelled(packet.context_id):
                return
            pcm, rate = from_wav(base64.b64decode(encoded))
            await self._on_packet(TextToSpeechAudioPacket(
                context_id=packet.context_id,
                audio=resample(pcm, rate, SAMPLE_RATE)))
        await self._on_packet(TextToSpeechAudioPacket(
            context_id=packet.context_id, audio=b"", is_final=True))


class ElevenLabsTTS(TextToSpeech):
    """ElevenLabs, streamed."""

    name = "elevenlabs"
    # 16 kHz PCM straight out, so no decode step and no resample.
    OUTPUT_FORMAT = "pcm_16000"
    #: "Rachel" — ElevenLabs' stock female voice, on every account including
    #: the free tier. Even and unhurried, which is what reading a threat
    #: assessment aloud needs. A key alone is therefore enough to get a good
    #: voice; ELEVENLABS_VOICE_ID only has to be set to get a *different* one.
    DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"

    def __init__(self, on_packet: OnPacket, *, voice: str = "",
                 language: str = "en-IN") -> None:
        super().__init__(
            on_packet,
            voice=voice or settings.ELEVENLABS_VOICE_ID or self.DEFAULT_VOICE,
            language=language)

    @staticmethod
    def available() -> bool:
        return bool(settings.ELEVENLABS_API_KEY)

    async def speak(self, packet: TextToSpeechTextPacket) -> None:
        if self.cancelled(packet.context_id) or not packet.text.strip():
            return
        url = f"{ELEVENLABS_URL}/{self.voice}/stream?output_format={self.OUTPUT_FORMAT}"
        body = {"text": packet.text[:1500],
                "model_id": settings.ELEVENLABS_MODEL,
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.75}}
        headers = {"xi-api-key": settings.ELEVENLABS_API_KEY,
                   "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=settings.VOICE_TTS_TIMEOUT) as client:
            async with client.stream("POST", url, json=body, headers=headers) as response:
                if response.status_code != 200:
                    detail = (await response.aread())[:200]
                    raise RuntimeError(f"HTTP {response.status_code}: {detail!r}")
                async for chunk in response.aiter_bytes(chunk_size=3200):
                    # Checked per chunk, not per sentence — this is what makes
                    # an interruption stop the voice inside 100 ms.
                    if self.cancelled(packet.context_id):
                        return
                    if chunk:
                        await self._on_packet(TextToSpeechAudioPacket(
                            context_id=packet.context_id, audio=chunk))
        await self._on_packet(TextToSpeechAudioPacket(
            context_id=packet.context_id, audio=b"", is_final=True))


_PROVIDERS: dict[str, type[TextToSpeech]] = {
    "browser": BrowserTTS,
    "sarvam": SarvamTTS,
    "elevenlabs": ElevenLabsTTS,
}

#: Best first. `browser` is last and always available, so the walk terminates.
#:
#: The two local neural voices used to sit in the middle of this ladder; see
#: the module docstring for why a hosted deployment has no offline tier.
_QUALITY_ORDER = ("elevenlabs", "sarvam", "browser")


def resolve(provider: str = "") -> str:
    """The provider name `create()` would choose, without building one."""
    requested = (provider or settings.VOICE_TTS_PROVIDER or "auto").lower()
    candidates = ([requested] + [p for p in _QUALITY_ORDER if p != requested]
                  if requested != "auto" else list(_QUALITY_ORDER))
    for name in candidates:
        factory = _PROVIDERS.get(name)
        if factory is None:
            continue
        checker = getattr(factory, "available", None)
        if checker is None or checker():
            return name
    return "browser"


def create(on_packet: OnPacket, provider: str = "", **kwargs) -> TextToSpeech:
    """Factory mirroring Rapida's `transformer.NewTextToSpeech`.

    `auto` — the default — walks the quality ladder and takes the first
    provider whose key is present. The alternative, naming one provider and
    erroring when it has no key, means a deployment that has not bought a
    speech key has no voice at all; this way the assistant always talks, and
    configuring a key upgrades it without touching code.
    """
    requested = (provider or settings.VOICE_TTS_PROVIDER or "auto").lower()
    pinned = requested != "auto"
    candidates = ([requested] + [p for p in _QUALITY_ORDER if p != requested]
                  if pinned else list(_QUALITY_ORDER))

    # A voice name lives in one provider's namespace, so it is honoured only by
    # the provider it was chosen for. Handing an ElevenLabs voice id to Sarvam
    # is a 400, not a fallback.
    voice = kwargs.pop("voice", "") or settings.VOICE_TTS_VOICE

    for name in candidates:
        factory = _PROVIDERS.get(name)
        if factory is None:
            continue
        checker = getattr(factory, "available", None)
        if checker is not None and not checker():
            continue
        if pinned and name != requested:
            log.warning("tts provider %r unavailable — using %r", requested, name)
        chosen = dict(kwargs)
        if voice and name == requested:
            chosen["voice"] = voice
        return factory(on_packet, **chosen)

    return BrowserTTS(on_packet, **kwargs)


def status() -> list[dict]:
    return [{"name": name,
             "available": not hasattr(factory, "available") or factory.available(),
             "client_side": factory.is_client_side}
            for name, factory in _PROVIDERS.items()]
