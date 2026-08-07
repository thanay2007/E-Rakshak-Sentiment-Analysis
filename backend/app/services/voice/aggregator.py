"""Sentence assembly — turning an LLM token stream into speakable units.

Ported from Rapida's `normalizer/output/aggregator/text_aggregator.go`,
including its multilingual boundary set.

The problem it solves is the one that decides whether a voice agent feels fast.
An LLM streams tokens: "In", " the", " last", " 24", " hours"… Synthesising
each token separately produces robotic, disjointed speech with a gap at every
word. Waiting for the complete answer before synthesising anything means the
officer stares at silence for the whole generation. Neither is acceptable.

So text is buffered until a sentence boundary, then that sentence is released
to be synthesised while the model is still generating the next one. Speech
starts after the first sentence and continues seamlessly — the officer hears
the answer begin roughly a second after asking, and generation latency for
everything after the first sentence disappears behind playback.

Two details carried over from Rapida because both are load-bearing:

  **The boundary set is multilingual.** `।` (Devanagari danda) and `۔` (Arabic
  full stop) are boundaries alongside `.`, and the CJK forms are kept too. An
  answer about a Gujarati post can come back with Devanagari punctuation, and
  a Latin-only boundary set buffers the entire response as one unit — silently
  turning streaming synthesis back into wait-for-everything.

  **Whitespace after the boundary is not consumed.** It is preserved as a
  leading space on the next chunk. Without it, TTS engines run the last word
  of one sentence into the first word of the next.

The abbreviation guard is an addition rather than a port: Rapida splits on any
boundary, which sends "Insp." to the synthesiser as a complete sentence and
produces an audible stumble. Given how many rank abbreviations this deployment
speaks, that was worth fixing here.
"""
from __future__ import annotations

import asyncio
import logging
import re

from app.services.voice.types import (LLMResponseDeltaPacket, LLMResponseDonePacket,
                                      OnPacket, Packet, TextToSpeechDonePacket,
                                      TextToSpeechTextPacket)

log = logging.getLogger("sentinel.voice.aggregator")

# Rapida's `sentenceBoundaries`, verbatim.
SENTENCE_BOUNDARIES = [
    ".", "!", "?", "|", ";", ":", "…",   # Latin / general
    "。", "．",                            # CJK full stop / fullwidth full stop
    "।",                                  # Devanagari danda
    "۔",                                  # Arabic full stop
]

# Whitespace after the boundary is deliberately NOT consumed — see the module
# docstring.
_BOUNDARY = re.compile("[" + re.escape("".join(SENTENCE_BOUNDARIES)) + "]")

# A full stop here ends a word, not a sentence. Ranks and honorifics dominate
# the list because this assistant speaks them constantly.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sh", "shri", "smt", "hon",
    "insp", "sub-insp", "asi", "psi", "dsp", "acp", "dcp", "addl", "supt",
    "sho", "ips", "ipc", "fir", "no", "nos", "sr", "jr", "st", "rd", "dept",
    "govt", "approx", "etc", "vs", "viz", "i.e", "e.g", "a.m", "p.m",
}

_TRAILING_WORD = re.compile(r"([\w'\-.]+)\s*$", re.UNICODE)

# A minimum length stops "Yes." and "OK." being shipped as their own
# synthesis request, which costs a round trip to say one word.
MIN_SENTENCE_CHARS = 12


class SentenceAggregator:
    """Buffers streamed text and emits complete sentences.

    Mirrors Rapida's `textAggregator`: a lock around the buffer, the callback
    invoked outside the lock so a slow consumer cannot deadlock the producer,
    and a context switch clearing state so two turns never blend.
    """

    name = "sentence_aggregator"

    def __init__(self, on_packet: OnPacket, *,
                 min_chars: int = MIN_SENTENCE_CHARS) -> None:
        self._on_packet = on_packet
        self._min_chars = min_chars
        self._buffer = ""
        self._context_id = ""
        self._lock = asyncio.Lock()
        self._closed = False

    # ── boundary logic ──────────────────────────────────────────────────────

    @staticmethod
    def _ends_with_abbreviation(text: str) -> bool:
        match = _TRAILING_WORD.search(text)
        if not match:
            return False
        word = match.group(1).rstrip(".").lower()
        if word in _ABBREVIATIONS:
            return True
        # A single letter before a full stop is an initial — "R. K. Patel" —
        # and splitting there breaks a name across two synthesis calls.
        return len(word) == 1 and word.isalpha()

    @staticmethod
    def _is_decimal_point(text: str, index: int) -> bool:
        """True for the dot in "67.4", which is not a sentence end.

        Scores are read aloud constantly here, and splitting inside one
        produces "sixty seven." … "four out of a hundred."
        """
        if index == 0 or index + 1 >= len(text):
            return False
        return text[index - 1].isdigit() and text[index + 1].isdigit()

    def _split(self, text: str) -> tuple[list[str], str]:
        """`(complete sentences, remainder)`."""
        sentences: list[str] = []
        start = 0
        for match in _BOUNDARY.finditer(text):
            index = match.start()
            if self._is_decimal_point(text, index):
                continue
            candidate = text[start:index + 1]
            if self._ends_with_abbreviation(candidate):
                continue
            if len(candidate.strip()) < self._min_chars:
                # Too short to be worth its own synthesis call — let it grow
                # and be emitted with the sentence that follows.
                continue
            sentences.append(candidate)
            start = index + 1
        return sentences, text[start:]

    # ── inbound ─────────────────────────────────────────────────────────────

    async def aggregate(self, *packets: Packet) -> None:
        if self._closed:
            return
        emit: list[Packet] = []

        async with self._lock:
            for packet in packets:
                if isinstance(packet, LLMResponseDeltaPacket):
                    if packet.context_id != self._context_id:
                        # A new turn. Anything buffered belongs to a turn that
                        # is over and must not be spoken into this one.
                        self._buffer = ""
                        self._context_id = packet.context_id
                    self._buffer += packet.text
                    sentences, self._buffer = self._split(self._buffer)
                    emit.extend(
                        TextToSpeechTextPacket(context_id=packet.context_id,
                                               text=sentence.strip())
                        for sentence in sentences if sentence.strip())

                elif isinstance(packet, LLMResponseDonePacket):
                    tail = (self._buffer + packet.text).strip() if packet.text \
                        else self._buffer.strip()
                    self._buffer = ""
                    self._context_id = packet.context_id
                    if tail:
                        emit.append(TextToSpeechTextPacket(
                            context_id=packet.context_id, text=tail))
                    emit.append(TextToSpeechDonePacket(
                        context_id=packet.context_id, text=tail))

        # Outside the lock, exactly as Rapida does it: the callback runs TTS,
        # which is slow, and holding the buffer lock across it would stall the
        # LLM stream feeding this.
        for packet in emit:
            await self._on_packet(packet)

    async def flush(self, context_id: str) -> None:
        """Emit whatever is buffered, complete sentence or not.

        For a response that ended without terminal punctuation — which happens
        whenever a model hits its token limit mid-clause.
        """
        async with self._lock:
            tail = self._buffer.strip()
            self._buffer = ""
        if tail:
            await self._on_packet(TextToSpeechTextPacket(context_id=context_id,
                                                         text=tail))
        await self._on_packet(TextToSpeechDonePacket(context_id=context_id,
                                                     text=tail))

    def reset(self) -> None:
        """Drop the buffer without emitting. Called on interruption — the
        officer is no longer interested in the rest of that sentence."""
        self._buffer = ""

    async def close(self) -> None:
        self._closed = True
        self._buffer = ""


def create(on_packet: OnPacket, **kwargs) -> SentenceAggregator:
    return SentenceAggregator(on_packet, **kwargs)
