"""Audio plumbing — resampling, framing, level metering.

Ported from Rapida's `internal/audio/`. Small, boring, and the source of most
voice-agent bugs that present as something else entirely:

  *A browser does not send 20 ms frames.* `ScriptProcessor` and `AudioWorklet`
  deliver 128, 1024 or 4096 samples depending on the browser and the machine's
  load. The VAD needs a fixed frame size or its probabilities are meaningless,
  so `FrameBuffer` re-cuts whatever arrives into exact 20 ms frames and keeps
  the remainder for next time.

  *A browser does not record at 16 kHz.* It records at the output device's
  rate — 44.1 or 48 kHz. Feeding 48 kHz audio to a recogniser expecting 16 kHz
  does not error; it transcribes a chipmunk. Resampling is therefore not
  optional and not a nicety.

  *Naive resampling aliases.* Dropping every third sample to get 48k → 16k
  folds everything above 8 kHz back down into the speech band as a metallic
  buzz, and word error rate climbs. `resample_poly` filters first, which is the
  entire difference.

The pipeline's internal format is fixed — 16 kHz, signed 16-bit little-endian,
mono — and every conversion happens here or in a transformer adapter, never in
between. That is what lets the VAD, the recogniser and the end-of-speech
detector all assume one format and be right.


Everything here is numpy rather than the stdlib `audioop` Rapida's equivalent
would reach for: PEP 594 removed that module in Python 3.13, which this project
runs. numpy is a hard dependency anyway via the NLP stack, so this costs
nothing and removes a version cliff.
"""
from __future__ import annotations

import logging
import math

import numpy as np

from app.services.voice.types import (CHANNELS, FRAME_BYTES, FRAME_SAMPLES,
                                      SAMPLE_RATE, SAMPLE_WIDTH)

log = logging.getLogger("sentinel.voice.audio")

try:                                    # scipy is present, but stay honest
    from scipy.signal import resample_poly
    _HAVE_SCIPY = True
except Exception:                       # pragma: no cover
    _HAVE_SCIPY = False
    log.warning("scipy unavailable — falling back to linear resampling")


# ── conversion ──────────────────────────────────────────────────────────────

def pcm16_to_float32(data: bytes) -> np.ndarray:
    """PCM16 bytes → float32 in [-1, 1], which is what every model wants."""
    if not data:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def float32_to_pcm16(samples: np.ndarray) -> bytes:
    """float32 → PCM16 bytes, clipped rather than wrapped.

    Clipping matters: a sample that overflows int16 wraps from +full-scale to
    -full-scale, which is an audible click on every overdriven frame rather
    than the mild distortion clipping gives you.
    """
    if samples.size == 0:
        return b""
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def to_mono(data: bytes, channels: int) -> bytes:
    """Average interleaved channels down to one.

    Averaged rather than left-channel-picked: a laptop with a stereo array
    microphone can put most of the speaker's energy in either channel
    depending on where they are sitting.
    """
    if channels <= 1 or not data:
        return data
    samples = np.frombuffer(data, dtype="<i2")
    usable = (samples.size // channels) * channels
    if usable == 0:
        return b""
    folded = samples[:usable].reshape(-1, channels).mean(axis=1)
    return folded.astype("<i2").tobytes()


def resample(data: bytes, source_rate: int, target_rate: int = SAMPLE_RATE) -> bytes:
    """Rate-convert PCM16, band-limiting on the way.

    `resample_poly` reduces the ratio to its lowest terms and applies an
    anti-aliasing FIR — 48000→16000 becomes a clean 1:3 decimation. The
    audioop fallback is there so a missing scipy degrades quality instead of
    breaking the feature.
    """
    if source_rate == target_rate or not data:
        return data
    samples = pcm16_to_float32(data)
    if _HAVE_SCIPY:
        gcd = math.gcd(source_rate, target_rate)
        resampled = resample_poly(samples, target_rate // gcd, source_rate // gcd)
        return float32_to_pcm16(np.asarray(resampled, dtype=np.float32))
    # Linear interpolation: no anti-aliasing, so downsampling folds high
    # frequencies into the speech band. Audible, and it costs word accuracy —
    # which is why scipy is the intended path and this only stops a missing
    # optional dependency from breaking the feature outright.
    count = max(1, int(round(samples.size * target_rate / source_rate)))
    source_positions = np.linspace(0, samples.size - 1, num=samples.size)
    target_positions = np.linspace(0, samples.size - 1, num=count)
    return float32_to_pcm16(np.interp(target_positions, source_positions,
                                      samples).astype(np.float32))


def normalise_inbound(data: bytes, source_rate: int, channels: int = 1) -> bytes:
    """Whatever the browser sent → the pipeline's one format."""
    return resample(to_mono(data, channels), source_rate, SAMPLE_RATE)


# ── framing ─────────────────────────────────────────────────────────────────

class FrameBuffer:
    """Re-cuts an arbitrary byte stream into exact 20 ms frames.

    Everything downstream — VAD probability, silence timing, interruption
    latency — is expressed in frames, so a frame has to be a fixed duration or
    those numbers mean nothing. This holds the remainder between calls, which
    is the whole job.
    """

    def __init__(self, frame_bytes: int = FRAME_BYTES) -> None:
        self._frame_bytes = frame_bytes
        self._buffer = bytearray()

    def push(self, data: bytes) -> list[bytes]:
        """Add bytes; return every complete frame now available."""
        self._buffer.extend(data)
        frames: list[bytes] = []
        while len(self._buffer) >= self._frame_bytes:
            frames.append(bytes(self._buffer[: self._frame_bytes]))
            del self._buffer[: self._frame_bytes]
        return frames

    def flush(self) -> bytes:
        """The trailing partial frame, zero-padded to full length.

        Called at end of utterance. Padding rather than discarding keeps the
        last consonant, which is otherwise the difference between "brief" and
        "brie".
        """
        if not self._buffer:
            return b""
        tail = bytes(self._buffer).ljust(self._frame_bytes, b"\x00")
        self._buffer.clear()
        return tail

    def reset(self) -> None:
        self._buffer.clear()

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)


# ── measurement ─────────────────────────────────────────────────────────────

def rms(data: bytes) -> float:
    """Root-mean-square level in [0, 1]. The energy VAD's whole input."""
    if len(data) < SAMPLE_WIDTH:
        return 0.0
    # Truncate an odd trailing byte rather than raising: a short read on the
    # websocket can split a sample across two messages, and that is a hiccup,
    # not an error worth propagating up the pipeline.
    usable = len(data) - (len(data) % SAMPLE_WIDTH)
    samples = np.frombuffer(data[:usable], dtype="<i2").astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples)))) / 32768.0


def dbfs(data: bytes) -> float:
    """Level in dBFS. Silence reports -100 rather than -inf so it can be
    averaged and compared without special-casing."""
    level = rms(data)
    return 20 * math.log10(level) if level > 1e-9 else -100.0


def duration_ms(data: bytes, sample_rate: int = SAMPLE_RATE) -> float:
    return 1000.0 * len(data) / (sample_rate * SAMPLE_WIDTH)


def silence(ms: float, sample_rate: int = SAMPLE_RATE) -> bytes:
    return b"\x00" * (int(sample_rate * ms / 1000) * SAMPLE_WIDTH)


# ── WAV container ───────────────────────────────────────────────────────────

def wav_header(data_length: int, sample_rate: int = SAMPLE_RATE,
               channels: int = CHANNELS) -> bytes:
    """A 44-byte RIFF header.

    Written by hand rather than with `wave` because the STT providers want a
    single in-memory buffer, and routing that through a file-like object to
    produce 44 known bytes is more machinery than the bytes themselves.
    """
    byte_rate = sample_rate * channels * SAMPLE_WIDTH
    block_align = channels * SAMPLE_WIDTH
    return b"".join([
        b"RIFF", (36 + data_length).to_bytes(4, "little"), b"WAVE",
        b"fmt ", (16).to_bytes(4, "little"),
        (1).to_bytes(2, "little"),                      # PCM
        channels.to_bytes(2, "little"),
        sample_rate.to_bytes(4, "little"),
        byte_rate.to_bytes(4, "little"),
        block_align.to_bytes(2, "little"),
        (SAMPLE_WIDTH * 8).to_bytes(2, "little"),
        b"data", data_length.to_bytes(4, "little"),
    ])


def to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE,
           channels: int = CHANNELS) -> bytes:
    return wav_header(len(pcm), sample_rate, channels) + pcm


def from_wav(payload: bytes) -> tuple[bytes, int]:
    """Strip a RIFF container, returning `(pcm, sample_rate)`.

    Chunks are walked rather than assumed at offset 44: providers emit `LIST`
    and `fact` chunks before `data`, and a fixed offset silently prepends a few
    hundred bytes of metadata to the audio as a burst of noise.
    """
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return payload, SAMPLE_RATE

    sample_rate = SAMPLE_RATE
    offset = 12
    while offset + 8 <= len(payload):
        chunk_id = payload[offset:offset + 4]
        size = int.from_bytes(payload[offset + 4:offset + 8], "little")
        body = offset + 8
        if chunk_id == b"fmt " and body + 8 <= len(payload):
            sample_rate = int.from_bytes(payload[body + 4:body + 8], "little")
        elif chunk_id == b"data":
            return payload[body:body + size], sample_rate
        offset = body + size + (size % 2)        # chunks are word-aligned
    return payload[44:], sample_rate


__all__ = [
    "FrameBuffer", "SAMPLE_RATE", "FRAME_BYTES", "FRAME_SAMPLES",
    "pcm16_to_float32", "float32_to_pcm16", "resample", "normalise_inbound",
    "rms", "dbfs", "duration_ms", "silence", "to_wav", "from_wav", "to_mono",
]
