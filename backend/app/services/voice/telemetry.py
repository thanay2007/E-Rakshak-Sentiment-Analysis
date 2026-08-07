"""Per-turn latency tracing.

Ported from Rapida's `internal/telemetry/`. A voice agent is judged almost
entirely on how long the silence is between the officer finishing their
question and hearing the first syllable back, and that silence is the sum of
five separate stages. When it is too long — and at some point it always is —
the only useful question is *which* stage, and without measurement the answer
is a guess.

So each turn records:

    listening   speech start → end of speech        turn-taking, tunable
    transcribe  end of speech → final transcript    the recogniser
    thinking    transcript → first LLM token        tools and model
    aggregate   first token → first full sentence   sentence assembly
    synthesise  first sentence → first audio        the synthesiser

`time_to_first_audio` is the number that matters and the one worth watching.
Under about 1.2 seconds a voice assistant feels like it is listening; over
about two it feels broken, and people start repeating themselves, which makes
it worse.

Everything is monotonic-clock based, in-memory, and bounded. This is
diagnostics, not an audit trail — what an officer asked is recorded by the
assistant router into the real audit log, and duplicating it here would put
transcripts somewhere with a weaker retention story.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger("sentinel.voice.telemetry")


@dataclass
class TurnTrace:
    """One question and its answer, measured."""

    context_id: str
    started_at: float = field(default_factory=time.monotonic)
    marks: dict[str, float] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    transcript_chars: int = 0
    reply_chars: int = 0
    interrupted: bool = False

    def mark(self, stage: str) -> None:
        """Stamp a stage the first time it happens.

        First-write-wins is deliberate: `first_audio` fires on every audio
        packet of the turn, and the interesting moment is the first one.
        """
        self.marks.setdefault(stage, time.monotonic())

    def _delta(self, start: str, end: str) -> float | None:
        if start not in self.marks or end not in self.marks:
            return None
        return round((self.marks[end] - self.marks[start]) * 1000, 1)

    @property
    def time_to_first_audio(self) -> float | None:
        """End of speech → first audio out. The number that matters."""
        return self._delta("end_of_speech", "first_audio")

    def summary(self) -> dict:
        return {
            "context_id": self.context_id,
            "transcribe_ms": self._delta("end_of_speech", "transcript"),
            "thinking_ms": self._delta("transcript", "first_token"),
            "aggregate_ms": self._delta("first_token", "first_sentence"),
            "synthesise_ms": self._delta("first_sentence", "first_audio"),
            "time_to_first_audio_ms": self.time_to_first_audio,
            "total_ms": self._delta("end_of_speech", "done"),
            "tools": self.tools,
            "transcript_chars": self.transcript_chars,
            "reply_chars": self.reply_chars,
            "interrupted": self.interrupted,
        }


class Telemetry:
    """Traces for one session. Bounded, because a shift is eight hours."""

    def __init__(self, keep: int = 20) -> None:
        self._traces: dict[str, TurnTrace] = {}
        self._order: deque[str] = deque(maxlen=keep)

    def begin(self, context_id: str) -> TurnTrace:
        trace = TurnTrace(context_id=context_id)
        self._traces[context_id] = trace
        self._order.append(context_id)
        # deque eviction does not touch the dict, so old traces would leak
        # without this.
        for stale in [k for k in self._traces if k not in self._order]:
            self._traces.pop(stale, None)
        return trace

    def get(self, context_id: str) -> TurnTrace | None:
        return self._traces.get(context_id)

    def mark(self, context_id: str, stage: str) -> None:
        trace = self._traces.get(context_id)
        if trace is not None:
            trace.mark(stage)

    def finish(self, context_id: str) -> dict | None:
        trace = self._traces.get(context_id)
        if trace is None:
            return None
        trace.mark("done")
        summary = trace.summary()
        first_audio = summary.get("time_to_first_audio_ms")
        if first_audio is not None and first_audio > 2000:
            # Worth a warning rather than a debug line: past two seconds the
            # officer has started repeating the question.
            log.warning("slow turn %s — %.0fms to first audio %s",
                        context_id, first_audio, summary)
        else:
            log.debug("turn %s %s", context_id, summary)
        return summary

    def recent(self, limit: int = 10) -> list[dict]:
        return [self._traces[c].summary()
                for c in list(self._order)[-limit:] if c in self._traces]

    def averages(self) -> dict:
        """Mean of each stage over the traces held. Shown on the diagnostics
        endpoint, where a single slow turn is noise and the average is not."""
        summaries = self.recent(limit=len(self._order))
        if not summaries:
            return {}
        keys = ("transcribe_ms", "thinking_ms", "aggregate_ms",
                "synthesise_ms", "time_to_first_audio_ms")
        out: dict[str, float | int] = {}
        for key in keys:
            values = [s[key] for s in summaries if s.get(key) is not None]
            if values:
                out[key] = round(sum(values) / len(values), 1)
        out["turns"] = len(summaries)
        return out
