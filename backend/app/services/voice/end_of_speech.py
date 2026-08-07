"""End of speech — deciding the officer has finished, not merely paused.

Ported from Rapida's `internal/end_of_speech/internal/silence_based/`, keeping
its structure: a segment accumulating transcript chunks, a generation counter,
and a timer that is rescheduled rather than reset on every new chunk.

The generation counter is the part worth copying carefully. Every new chunk of
transcript invalidates any timer already in flight by bumping a counter the
timer captured when it was scheduled; when it eventually fires it compares and
does nothing if it is stale. Without that, the naive implementation — cancel
the old timer, start a new one — races: the cancel and the fire can interleave
such that a segment is emitted while a later chunk is still arriving, and the
officer's question gets cut in half and answered twice.

Timing is the product decision here. Too short and the assistant interrupts
anyone who pauses to think, which reads as rude and makes people speak
unnaturally fast. Too long and every exchange has dead air. Rapida's default is
1000 ms and that is kept, with two adjustments this deployment needs:

  *Punctuation shortens the wait.* If the recogniser emitted a full stop, the
  speaker is very likely done, so the timeout drops. This is the single
  cheapest latency win available.

  *A trailing conjunction lengthens it.* "Show me Surat and..." is obviously
  unfinished. Waiting longer costs nothing when the speaker really was
  finished, and saves a wrong answer when they were not.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from app.services.voice.types import (EndOfSpeechPacket, InterimEndOfSpeechPacket,
                                      OnPacket, SpeechToTextPacket)

log = logging.getLogger("sentinel.voice.eos")

DEFAULT_SILENCE_TIMEOUT = 1.0          # Rapida's defaultSilenceTimeout
PUNCTUATED_TIMEOUT = 0.45
TRAILING_WORD_TIMEOUT = 1.8

# Sentence-final punctuation across the scripts this deployment sees. The
# Devanagari danda is not decorative here — a Hindi or Gujarati transcript ends
# with it and not with a full stop, so omitting it makes every Indic-language
# utterance wait the full timeout.
_TERMINAL = re.compile(r"[.!?。．।۔]\s*$")

# Words that mean the sentence is going somewhere. English plus the Hindi and
# Gujarati conjunctions that appear constantly in code-mixed speech.
_TRAILING = re.compile(
    r"\b(and|or|but|so|because|that|which|with|for|to|the|a|an|if|when|"
    r"aur|ane|ke|ka|ki|ne|ma|che|hai|nu|na)\s*$", re.IGNORECASE)


@dataclass
class _Segment:
    """Rapida's `speechSegment`: the utterance built so far."""
    context_id: str = ""
    text: str = ""
    chunks: list[SpeechToTextPacket] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)

    def add(self, packet: SpeechToTextPacket) -> None:
        self.chunks.append(packet)
        # Finals replace, interims append. A recogniser re-emits a growing
        # interim for the same words, so appending them all yields "show show
        # me show me surat"; the final is authoritative for what it covers.
        if packet.is_final:
            self.text = (self.text + " " + packet.text).strip()
        else:
            self.text = (self.text + " " + packet.text).strip() if not self.text \
                else self.text

    def clear(self) -> None:
        self.text = ""
        self.chunks.clear()
        self.started_at = time.monotonic()


class SilenceBasedEndOfSpeech:
    """The default detector, and the only one that needs no extra model."""

    name = "silence_based_eos"

    def __init__(self, on_packet: OnPacket, *,
                 silence_timeout: float = DEFAULT_SILENCE_TIMEOUT) -> None:
        self._on_packet = on_packet
        self._silence_timeout = silence_timeout
        self._segment = _Segment()
        self._generation = 0
        self._timer: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ── timeout selection ───────────────────────────────────────────────────

    def _timeout_for(self, text: str) -> float:
        """How long to wait, given what has been said so far."""
        stripped = text.strip()
        if not stripped:
            return self._silence_timeout
        if _TRAILING.search(stripped):
            return TRAILING_WORD_TIMEOUT
        if _TERMINAL.search(stripped):
            return PUNCTUATED_TIMEOUT
        return self._silence_timeout

    # ── the timer ───────────────────────────────────────────────────────────

    async def _fire_after(self, delay: float, generation: int, context_id: str) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        async with self._lock:
            # Stale: more speech arrived after this timer was scheduled. This
            # comparison is the whole reason for the generation counter.
            if generation != self._generation:
                return
            text = self._segment.text.strip()
            if not text:
                return
            self._segment.clear()
        await self._on_packet(EndOfSpeechPacket(context_id=context_id, text=text))

    def _schedule(self, delay: float, context_id: str) -> None:
        self._generation += 1
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        self._timer = asyncio.create_task(
            self._fire_after(delay, self._generation, context_id))

    # ── inbound transcript ──────────────────────────────────────────────────

    async def process(self, packet: SpeechToTextPacket) -> None:
        if not packet.text.strip():
            return
        async with self._lock:
            if self._segment.context_id != packet.context_id:
                self._segment = _Segment(context_id=packet.context_id)
            self._segment.add(packet)
            text = self._segment.text

        # Interims drive the on-screen live caption. They are emitted before
        # the timer is (re)scheduled so the interface stays ahead of the
        # decision rather than lagging it.
        if not packet.is_final:
            await self._on_packet(InterimEndOfSpeechPacket(
                context_id=packet.context_id, text=text))

        self._schedule(self._timeout_for(text), packet.context_id)

    async def flush(self, context_id: str) -> None:
        """Force the segment out now — the client said the utterance ended.

        Used when the officer releases push-to-talk, where waiting for silence
        is pointless: they have already told us they are done.
        """
        async with self._lock:
            self._generation += 1
            if self._timer is not None and not self._timer.done():
                self._timer.cancel()
            text = self._segment.text.strip()
            self._segment.clear()
        if text:
            await self._on_packet(EndOfSpeechPacket(context_id=context_id, text=text))

    async def interrupt(self, context_id: str) -> None:
        """Drop everything accumulated. The turn is being abandoned."""
        async with self._lock:
            self._generation += 1
            if self._timer is not None and not self._timer.done():
                self._timer.cancel()
            self._segment = _Segment(context_id=context_id)

    async def close(self) -> None:
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        self._timer = None


def create(on_packet: OnPacket, provider: str = "silence_based_eos", **kwargs):
    """Factory mirroring Rapida's `end_of_speech.New`.

    Rapida also offers LiveKit and Pipecat smart-turn detectors, which use a
    trained model to predict turn completion from prosody. Neither is ported:
    both need a model this deployment would have to ship, and the punctuation
    and conjunction heuristics above recover a good part of the benefit for the
    scripted, fairly formal way people talk to an operations console.
    """
    if provider not in ("", "silence_based_eos"):
        log.warning("end-of-speech provider %r is not available — using silence-based",
                    provider)
    return SilenceBasedEndOfSpeech(on_packet, **kwargs)
