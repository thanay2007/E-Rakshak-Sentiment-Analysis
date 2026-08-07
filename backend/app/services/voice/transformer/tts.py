"""Text-to-speech providers.

The default is `auto`: take the best voice this deployment actually has keys
for, and fall back rather than fail. In order of quality:

  **ElevenLabsTTS** — the best available, streamed so playback starts before
  synthesis finishes. The default voice is female and deliberately a calm,
  level one; an assistant that reads a threat score with enthusiasm is worse
  than one that reads it flatly.

  **SarvamTTS** — Indian-language voices. The one that pronounces "Vadodara"
  and "Rajkot" correctly, which every en-US voice gets wrong.

  **KokoroTTS** — a real neural voice that runs *on this machine*. No key, no
  network, no per-character cost, and nothing an officer asks is transmitted
  anywhere to be spoken. It is the only entry here that is simultaneously good
  and air-gappable, which for a police installation is the combination that
  matters: the two providers above it are better only while there is internet
  and a live account, and the one below it sounds like a screen reader.
  Apache-2.0 model, ONNX runtime, ~310 MB on disk, and it speaks Hindi as well
  as English (see LANGUAGES).

  **PiperHttpTTS** — a Piper voice served by a separate `piper` HTTP process.
  Smaller and faster than Kokoro on weak hardware, and the sensible choice for
  a site that already runs Piper. Deliberately the *HTTP* client and not the
  in-process library: `piper-tts` is GPL-3.0, and linking it into this backend
  would pull the whole application into the GPL's source-disclosure terms. Over
  HTTP it stays a separate program, which is exactly the boundary the licence
  turns on.

  **BrowserTTS** — emits the text with a flag and the browser speaks it. No
  key, no cost, no round trip, and the answer never leaves the machine, which
  in a police deployment is a real argument and not only a fallback. On
  Windows/Edge the voices it reaches are Microsoft's neural ones — the same
  engine a paid API would sell — so this is a good deal more than a stub. What
  it gives up is consistency: what an officer hears depends on their browser.

Neither local provider auto-downloads its model. A 310 MB fetch triggered by
the first sentence of a live call is a call that stalls for minutes and then
times out, and it would happen on the officer's first ever question. The files
are fetched once, deliberately, by `python -m app.services.voice.bootstrap`,
and until they exist the provider reports itself unavailable and the ladder
walks past it.

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

import asyncio
import logging
from pathlib import Path

import httpx

from app.config import settings
from app.services.voice.audio import float32_to_pcm16, from_wav, resample
from app.services.voice.transformer.base import TextToSpeech
from app.services.voice.types import (SAMPLE_RATE, OnPacket, TextToSpeechAudioPacket,
                                      TextToSpeechTextPacket)

log = logging.getLogger("sentinel.voice.tts")

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

#: Emitted per packet by the local synthesisers. 3200 bytes is 100 ms at 16 kHz
#: mono PCM16 — small enough that a barge-in is honoured within a tenth of a
#: second, large enough that a sentence is not thousands of websocket frames.
LOCAL_CHUNK_BYTES = 3200


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


class KokoroTTS(TextToSpeech):
    """Kokoro-82M through onnxruntime — a neural voice with no network at all.

    The model is loaded once per process and shared by every session. It is
    ~310 MB of weights and a second or two of startup, and a control room can
    have eight officers on the line at once; loading it per session would mean
    2.5 GB of identical weights and a multi-second pause before each first
    word. onnxruntime sessions are safe to call from several threads, which is
    what makes the sharing sound.

    Synthesis is blocking CPU work, so it runs in a worker thread. Doing it
    inline would freeze the event loop — and therefore *every other officer's*
    audio, the ingestion tick and the API — for the length of each sentence.
    """

    name = "kokoro"
    #: Kokoro's native output rate. Everything downstream is 16 kHz.
    NATIVE_RATE = 24_000
    #: Warm, level, and clear over a control-room speaker. Kokoro voice names
    #: encode language and gender: a=American, f=female / m=male.
    DEFAULT_VOICE = "af_heart"
    #: Hindi voices, used when the session is speaking Hindi. Kokoro has no
    #: Gujarati voice; Gujarati text is spoken by the Hindi voice, which shares
    #: most of its phoneme inventory and is far closer than any en-US voice.
    HINDI_VOICE = "hf_alpha"

    #: BCP-47-ish prefix → the espeak-ng locale kokoro-onnx phonemises with.
    #: Kokoro cannot do Gujarati, so `gu` is routed to Hindi rather than being
    #: read out as English letters.
    LANGUAGES = {"en": "en-us", "hi": "hi", "gu": "hi"}

    #: Process-wide, guarded because two sessions can open at the same instant
    #: and each would otherwise start its own 310 MB load.
    _model = None
    _model_lock = asyncio.Lock()

    def __init__(self, on_packet: OnPacket, *, voice: str = "",
                 language: str = "en-IN") -> None:
        super().__init__(on_packet, voice=voice, language=language)
        self.lang = self._resolve_language(language)
        # A caller-supplied voice wins; otherwise the voice follows the
        # language, because an American voice reading Hindi is unintelligible.
        self.voice = (voice or settings.KOKORO_VOICE
                      or (self.HINDI_VOICE if self.lang == "hi" else self.DEFAULT_VOICE))

    @classmethod
    def _resolve_language(cls, language: str) -> str:
        # `auto` means the recogniser decides per utterance and we cannot know
        # here; English is the right default for a Gujarat control room, whose
        # working language is English even when the posts are not.
        prefix = (language or "").lower().replace("_", "-").split("-")[0]
        return cls.LANGUAGES.get(prefix, "en-us")

    @staticmethod
    def model_files() -> tuple[Path, Path]:
        base = Path(settings.KOKORO_MODEL_DIR)
        return base / "kokoro-v1.0.onnx", base / "voices-v1.0.bin"

    @classmethod
    def available(cls) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
        except Exception:
            return False
        # Weights present, not merely importable — see the module docstring on
        # why nothing here downloads on demand.
        return all(p.exists() for p in cls.model_files())

    @classmethod
    async def load(cls):
        if cls._model is None:
            async with cls._model_lock:
                if cls._model is None:      # re-checked: another session may
                    from kokoro_onnx import Kokoro   # have won the lock
                    model, voices = cls.model_files()
                    log.info("kokoro: loading %s", model.name)
                    cls._model = await asyncio.to_thread(
                        Kokoro, str(model), str(voices))
        return cls._model

    async def speak(self, packet: TextToSpeechTextPacket) -> None:
        if self.cancelled(packet.context_id) or not packet.text.strip():
            return
        model = await self.load()
        if self.cancelled(packet.context_id):
            return

        # create_stream, not create: it splits the text into phoneme batches,
        # runs each in an executor, and yields as they finish. Two things come
        # from that, and both matter here. The inference never occupies the
        # event loop, so one officer's synthesis cannot stall another officer's
        # audio — and a long answer starts playing after its first batch
        # instead of after its last.
        stream = model.create_stream(packet.text[:1500], voice=self.voice,
                                     speed=1.0, lang=self.lang)
        async for samples, rate in stream:
            if self.cancelled(packet.context_id):
                return
            pcm = resample(float32_to_pcm16(samples), rate, SAMPLE_RATE)
            # Sliced further so an interruption lands mid-batch rather than
            # waiting out audio that has already been generated.
            for offset in range(0, len(pcm), LOCAL_CHUNK_BYTES):
                if self.cancelled(packet.context_id):
                    return
                await self._on_packet(TextToSpeechAudioPacket(
                    context_id=packet.context_id,
                    audio=pcm[offset:offset + LOCAL_CHUNK_BYTES]))
        await self._on_packet(TextToSpeechAudioPacket(
            context_id=packet.context_id, audio=b"", is_final=True))


class PiperHttpTTS(TextToSpeech):
    """A Piper voice served by a separate `piper --http` process.

    The HTTP boundary is a licensing decision, not an architectural one:
    `piper-tts` is GPL-3.0, so importing it here would put this backend under
    the GPL. A separate process spoken to over a socket is the arrangement the
    licence is written around, and it costs one localhost round trip.

    Piper answers with a WAV at the voice's own rate, usually 22.05 kHz.
    """

    name = "piper"

    def __init__(self, on_packet: OnPacket, *, voice: str = "",
                 language: str = "en-IN") -> None:
        super().__init__(on_packet, voice=voice or settings.PIPER_VOICE,
                         language=language)

    @staticmethod
    def available() -> bool:
        return bool(settings.PIPER_HTTP_URL)

    async def speak(self, packet: TextToSpeechTextPacket) -> None:
        if self.cancelled(packet.context_id) or not packet.text.strip():
            return
        params = {"voice": self.voice} if self.voice else None
        async with httpx.AsyncClient(timeout=settings.VOICE_TTS_TIMEOUT) as client:
            response = await client.post(
                settings.PIPER_HTTP_URL, params=params,
                content=packet.text[:1500].encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"})
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        if self.cancelled(packet.context_id):
            return

        pcm, rate = from_wav(response.content)
        pcm = resample(pcm, rate, SAMPLE_RATE)
        for offset in range(0, len(pcm), LOCAL_CHUNK_BYTES):
            if self.cancelled(packet.context_id):
                return
            await self._on_packet(TextToSpeechAudioPacket(
                context_id=packet.context_id,
                audio=pcm[offset:offset + LOCAL_CHUNK_BYTES]))
        await self._on_packet(TextToSpeechAudioPacket(
            context_id=packet.context_id, audio=b"", is_final=True))


_PROVIDERS: dict[str, type[TextToSpeech]] = {
    "browser": BrowserTTS,
    "kokoro": KokoroTTS,
    "piper": PiperHttpTTS,
    "sarvam": SarvamTTS,
    "elevenlabs": ElevenLabsTTS,
}

#: Best first. `browser` is last and always available, so the walk terminates.
#:
#: The two local voices sit above `browser` and below the paid ones. That is a
#: quality ordering and nothing else — a deployment that wants local *because*
#: it is local, rather than because it ran out of keys, pins
#: VOICE_TTS_PROVIDER=kokoro and the ladder is not consulted. Kokoro leads
#: Piper because it sounds better; Piper leads on hardware too weak for it.
_QUALITY_ORDER = ("elevenlabs", "sarvam", "kokoro", "piper", "browser")


def resolve(provider: str = "") -> str:
    """The provider name `create()` would choose, without building one.

    Separate from `create()` so the warm-up below can ask "will this
    deployment actually speak through Kokoro?" — loading 310 MB of weights on
    a box that has an ElevenLabs key and will never call Kokoro is pure waste.
    """
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


def warm_local_voice() -> None:
    """Start loading the local voice model now, off the critical path.

    Cold, Kokoro's first sentence costs several seconds of weight loading on
    top of synthesis. That cost lands on whoever speaks first — an officer,
    mid-shift, asking their first question — and a five-second silence does not
    read as "warming up", it reads as broken. Doing it at boot moves the wait
    somewhere nobody is listening.

    Fire-and-forget on purpose: the API must not wait for it, and a machine
    that cannot load the model should still start and fall back to a browser
    voice rather than refusing to boot over a nicety.
    """
    if not settings.VOICE_ENABLED or resolve() != "kokoro":
        return

    async def _warm() -> None:
        try:
            await KokoroTTS.load()
            log.info("kokoro: voice model resident — first reply will be prompt")
        except Exception:
            log.exception("kokoro: warm-up failed; the quality ladder will fall back")

    asyncio.get_running_loop().create_task(_warm())


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
