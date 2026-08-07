"""Voice activity detection — is anyone talking in this 20 ms?

Ported from Rapida's `internal/vad/`, which picks between Silero, TEN and
FireRed behind one interface. Two are shipped here: Silero, because torch is
already a dependency of this project and Silero is the model everyone actually
uses; and an energy detector, because the assistant has to work on a machine
where the model file was never downloaded.

The single most important thing in this file is not the detection — it is the
**hysteresis**. A raw per-frame verdict is useless directly: speech contains
pauses between words that are longer than 20 ms, so a detector that trusts each
frame reports speech starting and stopping several times per sentence, and the
end-of-speech layer downstream fires mid-sentence every time.

So a decision needs `speech_frames` consecutive positives to start and
`silence_frames` consecutive negatives to stop, and the two are deliberately
asymmetric. Starting is fast (about 60 ms) because latency to first word is
what makes an assistant feel responsive. Stopping is slow (about 500 ms)
because cutting someone off mid-thought is the failure people actually
complain about.

`is_interruption` is a separate, stricter question and has its own threshold.
Deciding to cut off the assistant mid-answer on the same evidence used to
notice a word has begun means a cough silences it.
"""
from __future__ import annotations

import logging

import numpy as np

from app.services.voice.audio import pcm16_to_float32, rms
from app.services.voice.types import (SAMPLE_RATE, DenoisedAudioPacket, OnPacket,
                                      VadSpeechActivityPacket)

log = logging.getLogger("sentinel.voice.vad")


class _Hysteresis:
    """Turns per-frame probabilities into a stable speech/not-speech state.

    Shared by both detectors so they behave identically at the boundary and a
    provider swap changes accuracy, not turn-taking feel.
    """

    def __init__(self, *, threshold: float, speech_frames: int,
                 silence_frames: int) -> None:
        self.threshold = threshold
        self._speech_frames = speech_frames
        self._silence_frames = silence_frames
        self._positive = 0
        self._negative = 0
        self.active = False

    def update(self, probability: float) -> bool:
        if probability >= self.threshold:
            self._positive += 1
            self._negative = 0
            if not self.active and self._positive >= self._speech_frames:
                self.active = True
        else:
            self._negative += 1
            self._positive = 0
            if self.active and self._negative >= self._silence_frames:
                self.active = False
        return self.active

    def reset(self) -> None:
        self._positive = self._negative = 0
        self.active = False


class EnergyVAD:
    """RMS against an adaptive noise floor.

    Crude, dependency-free, and good enough in a quiet room with a headset.
    The floor tracks the quietest recent frames so it survives a change of
    microphone or a fan switching on, and it only adapts downward quickly —
    adapting upward fast would let a long sentence raise the floor above the
    speaker's own voice and cut them off.
    """

    name = "energy_vad"

    def __init__(self, on_packet: OnPacket, *, threshold: float = 0.012,
                 speech_frames: int = 3, silence_frames: int = 25) -> None:
        self._on_packet = on_packet
        self._gate = _Hysteresis(threshold=0.5, speech_frames=speech_frames,
                                 silence_frames=silence_frames)
        self._base_threshold = threshold
        self._floor = threshold

    def probability(self, pcm: bytes) -> float:
        level = rms(pcm)
        # Track the floor downward quickly, upward slowly. See the docstring.
        if level < self._floor:
            self._floor = 0.9 * self._floor + 0.1 * level
        else:
            self._floor = 0.999 * self._floor + 0.001 * level
        threshold = max(self._base_threshold, self._floor * 3.0)
        if level <= threshold:
            return 0.0
        # Map "just over the threshold" → 0.5 and "well over" → ~1, so the
        # shared hysteresis sees a comparable scale from both detectors.
        return float(min(1.0, 0.5 + 0.5 * (level - threshold) / (threshold + 1e-6)))

    async def process(self, packet: DenoisedAudioPacket) -> None:
        probability = self.probability(packet.audio)
        active = self._gate.update(probability)
        await self._on_packet(VadSpeechActivityPacket(
            context_id=packet.context_id, audio=packet.audio,
            is_speech=active, probability=probability))

    def reset(self) -> None:
        self._gate.reset()

    async def close(self) -> None:
        return None


class SileroVAD:
    """Silero VAD via torch.

    The model wants exactly 512 samples at 16 kHz and returns a speech
    probability. Our frames are 320 samples (20 ms), so frames are accumulated
    into 512-sample windows and the last probability is held between windows —
    which is why `probability` on a given frame may repeat the previous value
    rather than being recomputed.

    Loading is lazy and failure is not fatal: `available()` returning False
    lets the factory fall back to energy detection rather than leaving the
    officer with no microphone because a model download failed.
    """

    name = "silero_vad"
    WINDOW = 512

    def __init__(self, on_packet: OnPacket, *, threshold: float = 0.5,
                 speech_frames: int = 3, silence_frames: int = 25) -> None:
        self._on_packet = on_packet
        self._gate = _Hysteresis(threshold=threshold, speech_frames=speech_frames,
                                 silence_frames=silence_frames)
        self._model = None
        self._pending = np.zeros(0, dtype=np.float32)
        self._last = 0.0

    @staticmethod
    def available() -> bool:
        try:
            import torch  # noqa: F401
            return True
        except Exception:
            return False

    def _load(self):
        if self._model is not None:
            return self._model
        import torch

        torch.set_num_threads(1)         # per-frame work; threading costs more
        model, _utils = torch.hub.load("snakers4/silero-vad", "silero_vad",
                                       trust_repo=True, onnx=False)
        model.eval()
        self._model = model
        return model

    def probability(self, pcm: bytes) -> float:
        import torch

        model = self._load()
        self._pending = np.concatenate([self._pending, pcm16_to_float32(pcm)])
        while self._pending.size >= self.WINDOW:
            window = self._pending[: self.WINDOW]
            self._pending = self._pending[self.WINDOW:]
            with torch.no_grad():
                self._last = float(model(torch.from_numpy(window), SAMPLE_RATE).item())
        return self._last

    async def process(self, packet: DenoisedAudioPacket) -> None:
        try:
            probability = self.probability(packet.audio)
        except Exception:
            log.exception("silero vad failed on a frame — treating as silence")
            probability = 0.0
        active = self._gate.update(probability)
        await self._on_packet(VadSpeechActivityPacket(
            context_id=packet.context_id, audio=packet.audio,
            is_speech=active, probability=probability))

    def reset(self) -> None:
        self._gate.reset()
        self._pending = np.zeros(0, dtype=np.float32)
        self._last = 0.0
        if self._model is not None:
            try:
                self._model.reset_states()
            except Exception:
                pass

    async def close(self) -> None:
        self._model = None


def create(on_packet: OnPacket, provider: str = "energy_vad", **kwargs):
    """Factory mirroring Rapida's `vad.New`.

    Silero is requested by name and silently degrades to energy detection if
    torch is missing. Degrading is right here: an assistant that hears you
    slightly worse is usable, and one that will not open the microphone is not.
    """
    if provider == "silero_vad":
        if SileroVAD.available():
            return SileroVAD(on_packet, **kwargs)
        log.warning("silero requested but torch is unavailable — using energy VAD")
    return EnergyVAD(on_packet, **kwargs)
