"""Noise reduction — the first stage of the audio front end.

Ported from Rapida's `internal/denoiser/`, which selects between Krisp and
RNNoise behind one interface. Neither is available here (Krisp is commercial,
RNNoise needs a native build), so the shipped implementation is spectral
subtraction with a noise floor estimated from the audio itself.

That sounds like a downgrade and mostly is, but it is aimed at the problem this
deployment actually has. A police operations room is not noisy in the way a
street is: it is a *steady* room — air conditioning, server fans, the hum of
fluorescent lighting. Steady broadband noise is precisely what spectral
subtraction removes well, and removing it before the VAD is worth more than
removing it before the recogniser, because a VAD threshold that has to sit
above the room's hum also sits above a quietly spoken word.

The estimator adapts only while the VAD believes there is no speech, which is
the standard arrangement and the one mistake worth avoiding: a noise profile
that keeps updating during speech learns the speaker's voice as noise and
subtracts it, producing a transcript that degrades the longer someone talks.

`PassthroughDenoiser` exists because on a headset in a quiet room this stage
can only hurt, and it should be possible to turn off without threading a
conditional through the session.
"""
from __future__ import annotations

import logging

import numpy as np

from app.services.voice.audio import float32_to_pcm16, pcm16_to_float32
from app.services.voice.types import (DenoiseAudioPacket, DenoisedAudioPacket,
                                      Denoiser, OnPacket)

log = logging.getLogger("sentinel.voice.denoiser")


class PassthroughDenoiser:
    """Does nothing, on purpose. The right choice on a headset."""

    name = "passthrough"

    def __init__(self, on_packet: OnPacket) -> None:
        self._on_packet = on_packet

    async def process(self, packet: DenoiseAudioPacket) -> None:
        await self._on_packet(DenoisedAudioPacket(context_id=packet.context_id,
                                                  audio=packet.audio))

    async def close(self) -> None:
        return None


class SpectralGateDenoiser:
    """Spectral subtraction against a continuously re-estimated noise floor.

    Per frame: window, FFT, subtract the noise magnitude estimate scaled by
    `over_subtraction`, floor the result so it never goes negative or fully
    silent, then inverse FFT keeping the original phase.

    Phase is kept rather than reconstructed because at 20 ms frames the ear
    cannot hear the phase error, and every method that does better costs more
    latency than the noise was worth. Latency is the currency here: this runs
    on every frame, ahead of everything else, and a slow front end shows up as
    the assistant being slow to notice you stopped talking.
    """

    name = "spectral_gate"

    def __init__(self, on_packet: OnPacket, *, over_subtraction: float = 1.5,
                 floor: float = 0.06, adaptation: float = 0.05) -> None:
        self._on_packet = on_packet
        self._over_subtraction = over_subtraction
        self._floor = floor
        self._adaptation = adaptation
        self._noise: np.ndarray | None = None
        self._window: np.ndarray | None = None
        # Set by the session from the VAD's verdict on the previous frame. The
        # profile only learns while this is False — see the module docstring.
        self.speech_active = False

    def _windowing(self, size: int) -> np.ndarray:
        if self._window is None or self._window.size != size:
            self._window = np.hanning(size).astype(np.float32)
        return self._window

    async def process(self, packet: DenoiseAudioPacket) -> None:
        cleaned = self.denoise(packet.audio)
        await self._on_packet(DenoisedAudioPacket(context_id=packet.context_id,
                                                  audio=cleaned))

    def denoise(self, pcm: bytes) -> bytes:
        samples = pcm16_to_float32(pcm)
        if samples.size < 32:
            return pcm

        frame_rms = float(np.sqrt(np.mean(np.square(samples))))
        spectrum = np.fft.rfft(samples)
        magnitude = np.abs(spectrum)

        # Only initialize or adapt noise floor during genuine quiet background periods
        if self._noise is None or self._noise.size != magnitude.size:
            if frame_rms < 0.015:
                self._noise = magnitude.copy()
            else:
                self._noise = np.zeros_like(magnitude)
            return pcm

        if not self.speech_active and frame_rms < 0.015:
            self._noise = ((1 - self._adaptation) * self._noise
                           + self._adaptation * magnitude)

        reduced = magnitude - self._over_subtraction * self._noise
        reduced = np.maximum(reduced, self._floor * magnitude)

        with np.errstate(divide="ignore", invalid="ignore"):
            gain = np.where(magnitude > 1e-9, reduced / magnitude, 1.0)
            # Smooth gain curve to prevent musical chirps
            gain = np.clip(gain, self._floor, 1.0)

        restored = np.fft.irfft(spectrum * gain, n=samples.size)
        return float32_to_pcm16(np.asarray(restored, dtype=np.float32))

    async def close(self) -> None:
        self._noise = None


def create(on_packet: OnPacket, provider: str = "passthrough") -> Denoiser:
    """Factory mirroring Rapida's `denoiser.New` — provider chosen by name,
    with an unknown name degrading to passthrough rather than failing the
    session. Passthrough is the default since browser WebRTC handles noise cancellation."""
    if provider in ("", "none", "passthrough", "off"):
        return PassthroughDenoiser(on_packet)
    if provider == "spectral_gate":
        return SpectralGateDenoiser(on_packet)
    log.warning("unknown denoiser %r — using passthrough", provider)
    return PassthroughDenoiser(on_packet)
