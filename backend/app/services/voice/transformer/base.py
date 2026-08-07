"""Provider adapters — the contract every recogniser and synthesiser meets.

Ported from Rapida's `internal/transformer/`, which has twenty-odd providers
behind two interfaces. The value is not the provider count; it is that the
session never learns which one it got. Whisper-on-Groq, Whisper-running-locally
and the browser's own recogniser all emit `SpeechToTextPacket`, so switching
between them changes cost and accuracy and nothing else.

Two shapes exist, and the difference decides how the session behaves:

  **Streaming.** Audio goes in continuously, interim transcripts come back
  while the officer is still talking. This is what makes a live caption
  possible and lets end-of-speech see punctuation early.

  **Batch.** Audio is buffered until the utterance ends, then sent in one
  request. Higher latency and no interims — but it is what the affordable
  providers offer, and Whisper is batch-only by construction.

`is_streaming` is on the interface rather than inferred because the session
uses it to decide whether to show a live caption at all. Showing an empty
caption box that only fills in after the officer stops talking is worse than
not showing one.

The base class handles the parts every adapter would otherwise repeat: bounding
how much audio may buffer, refusing to transcribe a fragment too short to
contain a word, and never letting a provider failure escape as an exception
into the packet router.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.services.voice.audio import duration_ms
from app.services.voice.types import (OnPacket, SpeechToTextAudioPacket,
                                      SpeechToTextErrorPacket, SpeechToTextPacket,
                                      TextToSpeechTextPacket)

log = logging.getLogger("sentinel.voice.transformer")

# Below this, a "transcript" is a hallucination. Whisper in particular invents
# plausible sentences from a fragment of breath — famously "Thank you." and
# "Subtitles by the Amara.org community" — and an assistant that answers those
# is worse than one that ignores them.
MIN_UTTERANCE_MS = 320.0

# Above this, stop buffering. A microphone left open against a running
# television produces unbounded audio, and the request that eventually carries
# it would time out anyway.
MAX_UTTERANCE_MS = 30_000.0


class SpeechToText(ABC):
    """A recogniser."""

    name = "base"
    is_streaming = False
    #: Providers that hallucinate on silence declare it, so the base class can
    #: apply the phrase filter without hard-coding Whisper's quirks everywhere.
    hallucinates_on_silence = False

    def __init__(self, on_packet: OnPacket, *, language: str = "en-IN") -> None:
        self._on_packet = on_packet
        self.language = language
        self._buffer = bytearray()

    # ── buffering, shared by every batch adapter ────────────────────────────

    async def feed(self, packet: SpeechToTextAudioPacket) -> None:
        self._buffer.extend(packet.audio)
        if duration_ms(bytes(self._buffer)) >= MAX_UTTERANCE_MS:
            log.warning("%s: utterance exceeded %.0fs — transcribing early",
                        self.name, MAX_UTTERANCE_MS / 1000)
            await self.flush(packet.context_id)

    async def flush(self, context_id: str) -> None:
        audio = bytes(self._buffer)
        self._buffer.clear()
        if duration_ms(audio) < MIN_UTTERANCE_MS:
            return
        try:
            text, confidence, language = await self.transcribe(audio)
        except Exception as exc:
            log.exception("%s transcription failed", self.name)
            await self._on_packet(SpeechToTextErrorPacket(
                context_id=context_id, message=f"{self.name}: {exc}"))
            return

        text = (text or "").strip()
        if not text or self._is_hallucination(text):
            return
        await self._on_packet(SpeechToTextPacket(
            context_id=context_id, text=text, is_final=True,
            confidence=confidence, language=language or self.language))

    def _is_hallucination(self, text: str) -> bool:
        if not self.hallucinates_on_silence:
            return False
        return text.strip().lower().strip(".!? ") in _SILENCE_HALLUCINATIONS

    def reset(self) -> None:
        self._buffer.clear()

    @abstractmethod
    async def transcribe(self, audio: bytes) -> tuple[str, float, str]:
        """16 kHz mono PCM16 in → `(text, confidence, language)` out."""

    async def close(self) -> None:
        self._buffer.clear()


# What Whisper says when handed silence or noise. Matched exactly rather than
# by substring: "thank you" is a legitimate thing for an officer to say, and
# only a transcript that is *entirely* this phrase is suspect.
_SILENCE_HALLUCINATIONS = frozenset({
    "thank you", "thanks", "thanks for watching", "thank you for watching",
    "you", "bye", "bye bye", "please subscribe", "subtitles by the amara.org "
    "community", "subs by www.zeoranger.co.uk", "transcription by castingwords",
    "okay", "ok", "mm", "mmm", "hmm", "uh", "um", "ah", "oh", ".", "...",
    "music", "applause", "silence", "foreign", "so",
})


class TextToSpeech(ABC):
    """A synthesiser."""

    name = "base"
    #: When true the session tells the browser to speak the text itself and no
    #: audio crosses the network. Not a real provider — an escape hatch that
    #: keeps voice output working with no API key configured at all.
    is_client_side = False

    def __init__(self, on_packet: OnPacket, *, voice: str = "",
                 language: str = "en-IN") -> None:
        self._on_packet = on_packet
        self.voice = voice
        self.language = language
        #: Set by the session on interruption. Every adapter checks it between
        #: chunks, which is what makes barge-in feel immediate rather than
        #: waiting for the provider to acknowledge a cancel.
        self._cancelled: set[str] = set()

    @abstractmethod
    async def speak(self, packet: TextToSpeechTextPacket) -> None:
        """Synthesise one sentence, emitting `TextToSpeechAudioPacket`s."""

    async def interrupt(self, context_id: str) -> None:
        self._cancelled.add(context_id)

    def cancelled(self, context_id: str) -> bool:
        return context_id in self._cancelled

    def clear(self, context_id: str) -> None:
        self._cancelled.discard(context_id)

    async def close(self) -> None:
        self._cancelled.clear()
