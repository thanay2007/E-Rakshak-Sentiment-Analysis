"""The real-time voice pipeline.

A port of Rapida's `api/assistant-api/internal/` voice agent — the packet
router, the audio front end, turn-taking, streaming synthesis and the provider
adapters — from Go into this project's Python.

    types.py        the packet vocabulary every component speaks
    audio.py        resampling, 20 ms framing, level metering
    denoiser.py     spectral-subtraction noise reduction
    vad.py          voice activity detection with hysteresis
    end_of_speech.py    silence-based turn completion
    aggregator.py   streamed tokens → speakable sentences
    normalizer/     text as written → text as spoken
    transformer/    speech-to-text and text-to-speech providers
    state.py        turn state and the barge-in decision
    telemetry.py    per-turn latency tracing
    session.py      the central packet router and session lifecycle

The architectural idea, and the reason it is worth porting rather than
approximating: **components never call each other.** Each is constructed with
one `on_packet` callback and emits into it. `session.py` decides what every
packet means. That indirection is what makes interruption a single branch
instead of a cancellation tangle, and what lets any provider be swapped without
anything downstream noticing.

The safety boundary is not in this package. Voice is a transport: a spoken
question goes through the same `services/assistant` guard, the same
rank-filtered tools and the same audit write as a typed one. Adding a
microphone did not add a capability.
"""
from app.services.voice import (aggregator, audio, denoiser, end_of_speech,  # noqa: F401
                                normalizer, state, telemetry, transformer,
                                types, vad)
from app.services.voice.session import SessionConfig, VoiceSession  # noqa: F401

__all__ = ["VoiceSession", "SessionConfig", "types", "audio", "denoiser",
           "vad", "end_of_speech", "aggregator", "normalizer", "transformer",
           "state", "telemetry"]
