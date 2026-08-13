"""Packets and component contracts — the vocabulary the whole pipeline speaks.

Ported from Rapida's `api/assistant-api/internal/type/`. The idea it carries
over, and the reason it is worth copying rather than inventing something
simpler, is this: **every component is deaf to every other component.** The VAD
does not call the STT. It emits a packet. A single router decides what that
packet means and who hears it next.

That indirection buys the two things a voice agent lives or dies on:

  *Interruption.* When the officer starts talking over an answer, one packet
  (`InterruptionDetected`) has to stop the LLM, stop the TTS, drop the audio
  already queued for playback, and roll the turn back — four components, none
  of which knows about the others. With direct calls that is a tangle of
  cancellation plumbing. With packets it is one router branch.

  *Substitution.* Whisper-on-Groq and Whisper-running-locally emit the same
  `SpeechToText` packet, so which one is configured changes nothing downstream.
  Same for the four TTS providers, the two VADs and the two denoisers.

Rapida's naming convention is kept because it earns its keep once there are
forty packet types:

    Commands  (do this)         verb first — ExecuteLLM, SpeakText, InterruptTTS
    Events    (this happened)   past tense — SpeechToText, EndOfSpeech, DenoisedAudio

Audio is 16 kHz signed 16-bit little-endian mono everywhere inside the
pipeline, exactly as it is in Rapida. Conversion to and from whatever the
browser or a provider wants happens at the edges, in `audio.py` and in the
transformer adapters — never in between.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

# ── the one audio format the pipeline knows ─────────────────────────────────

SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2          # bytes; signed 16-bit
CHANNELS = 1
FRAME_MS = 20             # Rapida's frame size, and what WebRTC/Opus expect
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000        # 320
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH            # 640


def new_context_id() -> str:
    """A turn identifier.

    One per user utterance, carried by every packet that utterance produces.
    It is what lets a late packet from an interrupted turn be recognised and
    dropped: audio synthesised for turn 7 must never play after the officer has
    already started turn 8.
    """
    return uuid.uuid4().hex[:16]


# ── packet names ────────────────────────────────────────────────────────────

class PacketName(str, Enum):
    # session lifecycle
    INITIALIZE_SESSION = "InitializeSessionPacket"
    INITIALIZATION_COMPLETED = "InitializationCompletedPacket"
    SESSION_CLOSED = "SessionClosedPacket"

    # inbound from the client
    USER_AUDIO_RECEIVED = "UserAudioReceivedPacket"
    USER_TEXT_RECEIVED = "UserTextReceivedPacket"

    # audio front end
    DENOISE_AUDIO = "DenoiseAudioPacket"
    DENOISED_AUDIO = "DenoisedAudioPacket"
    VAD_SPEECH_ACTIVITY = "VadSpeechActivityPacket"

    # speech to text
    SPEECH_TO_TEXT_AUDIO = "SpeechToTextAudioPacket"
    SPEECH_TO_TEXT = "SpeechToTextPacket"
    SPEECH_TO_TEXT_ERROR = "SpeechToTextErrorPacket"

    # turn taking
    END_OF_SPEECH = "EndOfSpeechPacket"
    INTERIM_END_OF_SPEECH = "InterimEndOfSpeechPacket"
    INTERRUPTION_DETECTED = "InterruptionDetectedPacket"
    TURN_CHANGE = "TurnChangePacket"
    WAKE_STATE = "WakeStatePacket"

    # the assistant
    EXECUTE_LLM = "ExecuteLLMPacket"
    LLM_RESPONSE_DELTA = "LLMResponseDeltaPacket"
    LLM_RESPONSE_DONE = "LLMResponseDonePacket"
    LLM_TOOL_INVOKED = "LLMToolInvokedPacket"
    LLM_INTERRUPT = "LLMInterruptPacket"
    LLM_NAVIGATE = "LLMNavigatePacket"

    # text to speech
    TEXT_TO_SPEECH_TEXT = "TextToSpeechTextPacket"
    TEXT_TO_SPEECH_DONE = "TextToSpeechDonePacket"
    TEXT_TO_SPEECH_AUDIO = "TextToSpeechAudioPacket"
    TEXT_TO_SPEECH_INTERRUPT = "TextToSpeechInterruptPacket"

    # behaviours
    INJECT_MESSAGE = "InjectMessagePacket"
    IDLE_TIMEOUT = "IdleTimeoutPacket"
    MAX_SESSION_REACHED = "MaxSessionReachedPacket"

    # diagnostics
    PIPELINE_ERROR = "PipelineErrorPacket"
    TELEMETRY = "TelemetryPacket"


# ── base ────────────────────────────────────────────────────────────────────

@dataclass
class Packet:
    """Everything that moves through the pipeline.

    `context_id` binds a packet to one turn; `created_at` is what the telemetry
    layer measures latency from, so it is stamped at construction rather than
    when the packet is handled.
    """
    context_id: str = field(default_factory=new_context_id)
    created_at: float = field(default_factory=time.monotonic)

    @property
    def name(self) -> PacketName:  # pragma: no cover — every subclass overrides
        raise NotImplementedError


def _packet(name: PacketName):
    """Attach a packet name to a dataclass without repeating the property."""
    def decorate(cls):
        cls.name = property(lambda self, _n=name: _n)
        cls.PACKET_NAME = name
        return cls
    return decorate


# ── session lifecycle ───────────────────────────────────────────────────────

@_packet(PacketName.INITIALIZE_SESSION)
@dataclass
class InitializeSessionPacket(Packet):
    page: str = ""
    language: str = "en-IN"


@_packet(PacketName.INITIALIZATION_COMPLETED)
@dataclass
class InitializationCompletedPacket(Packet):
    stt_provider: str = ""
    tts_provider: str = ""
    vad_provider: str = ""
    greeting: str = ""


@_packet(PacketName.SESSION_CLOSED)
@dataclass
class SessionClosedPacket(Packet):
    reason: str = ""


# ── inbound ─────────────────────────────────────────────────────────────────

@_packet(PacketName.USER_AUDIO_RECEIVED)
@dataclass
class UserAudioReceivedPacket(Packet):
    """One frame of microphone audio, already 16 kHz mono PCM16."""
    audio: bytes = b""


@_packet(PacketName.USER_TEXT_RECEIVED)
@dataclass
class UserTextReceivedPacket(Packet):
    """A typed question. Enters the pipeline at the same point a finalised
    transcript does, so typing and speaking cannot drift apart in behaviour."""
    text: str = ""


# ── audio front end ─────────────────────────────────────────────────────────

@_packet(PacketName.DENOISE_AUDIO)
@dataclass
class DenoiseAudioPacket(Packet):
    audio: bytes = b""


@_packet(PacketName.DENOISED_AUDIO)
@dataclass
class DenoisedAudioPacket(Packet):
    audio: bytes = b""


@_packet(PacketName.VAD_SPEECH_ACTIVITY)
@dataclass
class VadSpeechActivityPacket(Packet):
    """Per-frame verdict from the VAD.

    `probability` is kept alongside the boolean because the interruption
    threshold is deliberately stricter than the speech-start threshold — a
    cough should not cut off an answer mid-sentence.
    """
    audio: bytes = b""
    is_speech: bool = False
    probability: float = 0.0


# ── speech to text ──────────────────────────────────────────────────────────

@_packet(PacketName.SPEECH_TO_TEXT_AUDIO)
@dataclass
class SpeechToTextAudioPacket(Packet):
    """Audio the VAD has accepted as speech, on its way to the recogniser."""
    audio: bytes = b""


@_packet(PacketName.SPEECH_TO_TEXT)
@dataclass
class SpeechToTextPacket(Packet):
    text: str = ""
    is_final: bool = False
    confidence: float = 0.0
    language: str = ""


@_packet(PacketName.SPEECH_TO_TEXT_ERROR)
@dataclass
class SpeechToTextErrorPacket(Packet):
    message: str = ""


# ── turn taking ─────────────────────────────────────────────────────────────

@_packet(PacketName.END_OF_SPEECH)
@dataclass
class EndOfSpeechPacket(Packet):
    """The officer has stopped talking and the utterance is complete."""
    text: str = ""


@_packet(PacketName.INTERIM_END_OF_SPEECH)
@dataclass
class InterimEndOfSpeechPacket(Packet):
    text: str = ""


@_packet(PacketName.INTERRUPTION_DETECTED)
@dataclass
class InterruptionDetectedPacket(Packet):
    """The officer started talking while the assistant was talking.

    The single most important packet in the pipeline. Everything downstream of
    it is a cancellation, and a voice agent that handles this badly is one
    nobody uses twice.
    """
    reason: str = "barge_in"


@_packet(PacketName.TURN_CHANGE)
@dataclass
class TurnChangePacket(Packet):
    speaker: str = "assistant"      # "user" | "assistant"


@_packet(PacketName.WAKE_STATE)
@dataclass
class WakeStatePacket(Packet):
    """Whether the officer currently has to say the name to be heard.

    Sent because a gate nobody was told about is indistinguishable from a
    broken microphone. The officer needs to see the difference between "say
    Sentinel first" and "go ahead, I'm still with you", and only the server
    knows which is true — the follow-up window opens and closes here.

    Deriving it client-side from a timer was the alternative and it would drift:
    the window is extended by speech the browser does not adjudicate, so the two
    clocks would disagree exactly when an officer is mid-conversation.
    """
    #: True while the follow-up window is open — no wake word needed.
    listening: bool = False
    #: False when the gate is off entirely, so the client can stop mentioning it.
    required: bool = True
    phrase: str = "Sentinel"
    #: Seconds the window has left. The client counts this down to flip its own
    #: label; every extension sends a fresh packet, so the countdown is reset
    #: rather than allowed to drift away from the server's.
    expires_in: float = 0.0


# ── the assistant ───────────────────────────────────────────────────────────

@_packet(PacketName.EXECUTE_LLM)
@dataclass
class ExecuteLLMPacket(Packet):
    text: str = ""


@_packet(PacketName.LLM_RESPONSE_DELTA)
@dataclass
class LLMResponseDeltaPacket(Packet):
    text: str = ""


@_packet(PacketName.LLM_RESPONSE_DONE)
@dataclass
class LLMResponseDonePacket(Packet):
    text: str = ""
    intent: str = ""
    source: str = ""


@_packet(PacketName.LLM_TOOL_INVOKED)
@dataclass
class LLMToolInvokedPacket(Packet):
    """Emitted per tool so the interface can show its working while the answer
    is still being composed — the officer sees "checking alerts" rather than a
    spinner."""
    tool: str = ""
    arguments: dict = field(default_factory=dict)
    display: dict = field(default_factory=dict)


@_packet(PacketName.LLM_INTERRUPT)
@dataclass
class LLMInterruptPacket(Packet):
    pass


@_packet(PacketName.LLM_NAVIGATE)
@dataclass
class LLMNavigatePacket(Packet):
    """Only ever produced by the assistant's `navigate` tool resolving a fixed
    label against a fixed table. A path never originates in model prose."""
    path: str = ""


# ── text to speech ──────────────────────────────────────────────────────────

@_packet(PacketName.TEXT_TO_SPEECH_TEXT)
@dataclass
class TextToSpeechTextPacket(Packet):
    """One complete, normalised sentence, ready to be spoken."""
    text: str = ""


@_packet(PacketName.TEXT_TO_SPEECH_DONE)
@dataclass
class TextToSpeechDonePacket(Packet):
    text: str = ""


@_packet(PacketName.TEXT_TO_SPEECH_AUDIO)
@dataclass
class TextToSpeechAudioPacket(Packet):
    audio: bytes = b""
    sample_rate: int = SAMPLE_RATE
    is_final: bool = False


@_packet(PacketName.TEXT_TO_SPEECH_INTERRUPT)
@dataclass
class TextToSpeechInterruptPacket(Packet):
    pass


# ── behaviours ──────────────────────────────────────────────────────────────

@_packet(PacketName.INJECT_MESSAGE)
@dataclass
class InjectMessagePacket(Packet):
    """Something the assistant should say that no question asked for — the
    greeting, an idle nudge, a live critical alert."""
    text: str = ""
    kind: str = "system"


@_packet(PacketName.IDLE_TIMEOUT)
@dataclass
class IdleTimeoutPacket(Packet):
    seconds: float = 0.0


@_packet(PacketName.MAX_SESSION_REACHED)
@dataclass
class MaxSessionReachedPacket(Packet):
    seconds: float = 0.0


# ── diagnostics ─────────────────────────────────────────────────────────────

@_packet(PacketName.PIPELINE_ERROR)
@dataclass
class PipelineErrorPacket(Packet):
    component: str = ""
    message: str = ""


@_packet(PacketName.TELEMETRY)
@dataclass
class TelemetryPacket(Packet):
    stage: str = ""
    elapsed_ms: float = 0.0
    detail: dict = field(default_factory=dict)


# ── component contracts ─────────────────────────────────────────────────────

OnPacket = Callable[..., Awaitable[None]]
"""Every component is constructed with one of these and emits through it.

A component never holds a reference to another component, only to this. It is
the whole reason a provider can be swapped without touching anything
downstream — see the module docstring.
"""


@runtime_checkable
class Component(Protocol):
    """Lifecycle shared by everything in the pipeline."""

    async def close(self) -> None: ...


# The three Protocols below are the contracts `denoiser.create`,
# `vad.create` and `end_of_speech.create` are annotated with: each of those
# picks between implementations that share no base class, so the Protocol is
# what says they are interchangeable. (Recognisers and synthesisers do have a
# shared base - transformer/base.py - so they need no Protocol here.)
@runtime_checkable
class Denoiser(Component, Protocol):
    async def process(self, packet: DenoiseAudioPacket) -> None: ...


@runtime_checkable
class VoiceActivityDetector(Component, Protocol):
    async def process(self, packet: DenoisedAudioPacket) -> None: ...


@runtime_checkable
class EndOfSpeechDetector(Component, Protocol):
    async def process(self, packet: SpeechToTextPacket) -> None: ...
    async def interrupt(self, context_id: str) -> None: ...


@runtime_checkable
class TextNormalizer(Protocol):
    """Pure text in, pure text out. Deliberately synchronous and stateless so
    the chain is trivially testable and order-independent to reason about."""

    name: str

    def normalize(self, text: str) -> str: ...


def describe(packet: Packet) -> dict[str, Any]:
    """A log-safe view of a packet.

    Audio is reduced to a byte count: logging a frame is useless to read and
    turns a debug session into gigabytes. Text is truncated, because a
    transcript is evidence and belongs in the audit trail, not the log file.
    """
    out: dict[str, Any] = {"packet": packet.name.value, "context": packet.context_id}
    for key, value in vars(packet).items():
        if key in ("context_id", "created_at"):
            continue
        if isinstance(value, (bytes, bytearray)):
            out[f"{key}_bytes"] = len(value)
        elif isinstance(value, str):
            out[key] = value[:80]
        else:
            out[key] = value
    return out
