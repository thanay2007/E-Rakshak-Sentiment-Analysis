"""Turn state — who is talking, and what an interruption means right now.

Ported from Rapida's `adapters/customizers/messaging.go`, which is a small
state machine doing a job that is much harder than it looks.

The naive version of barge-in is "if the VAD says the user is talking while the
assistant is talking, cancel everything". It fails in four ways, all of which
happen constantly in a real room:

  **The assistant hears itself.** Speakers feed the microphone. Without
  suppression the assistant's own voice trips the VAD and it interrupts itself
  mid-sentence, every sentence. This is the failure that makes people give up
  on a voice agent in the first minute. Suppressing it needs a fact the server
  does not have — whether sound is coming out of the speakers *now*, which is
  not the same as whether the server has finished sending audio — so the
  browser reports it and `set_client_playback` is where it lands.

  **A cough is not an interruption.** One frame over the threshold cannot be
  allowed to cut off an answer. Interruption needs sustained speech —
  materially more evidence than "someone made a sound".

  **The first word is not an interruption either.** For a moment after the
  assistant starts speaking, the audio still in the playback buffer is the
  *previous* turn's. Reacting during that window cancels a turn that had not
  started.

  **Cancelling is not one action.** The LLM, the aggregator, the synthesiser
  and the playback queue all have to stop, and audio already synthesised must
  be discarded on arrival. That last part is why every packet carries a context
  id and why `is_stale()` exists.

So the machine has four states and the transitions are the interesting part:

    IDLE ──user speaks──▶ LISTENING ──end of speech──▶ THINKING
      ▲                                                    │
      │                                              first sentence
      └──────done / interrupted──── SPEAKING ◀──────────────┘

`SPEAKING` is the only state where an interruption is meaningful, and even
there it is gated on a grace period and a sustained-speech count.
"""
from __future__ import annotations

import logging
import time
from enum import Enum

log = logging.getLogger("sentinel.voice.state")

#: How long after the assistant starts speaking before an interruption counts.
#: Covers the audio already in the client's playback buffer.
INTERRUPT_GRACE_SECONDS = 0.45

#: Consecutive speech frames (20 ms each) needed to interrupt. Fifteen frames
#: is 300 ms — long enough to exclude a cough or a chair scrape, short enough
#: that talking over the assistant feels like it works immediately.
INTERRUPT_SPEECH_FRAMES = 15

#: Probability an inbound frame must clear to count toward an interruption.
#: Deliberately higher than the VAD's own speech threshold: cutting the
#: assistant off needs better evidence than noticing a word has begun.
INTERRUPT_PROBABILITY = 0.75

#: How long after the officer's speakers actually go quiet the microphone stays
#: gated. Covers the room's reverberation tail and the frames that were already
#: in flight when the last sample played.
PLAYBACK_HANGOVER_SECONDS = 0.4


class TurnState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class ConversationState:
    """The state machine. One per session, driven entirely by the packet router."""

    def __init__(self, *, grace_seconds: float = INTERRUPT_GRACE_SECONDS,
                 interrupt_frames: int = INTERRUPT_SPEECH_FRAMES,
                 interrupt_probability: float = INTERRUPT_PROBABILITY) -> None:
        self.state = TurnState.IDLE
        self.context_id = ""
        self._grace = grace_seconds
        self._required_frames = interrupt_frames
        self._probability = interrupt_probability

        self._speaking_since = 0.0
        self._consecutive = 0
        self._interrupted_contexts: set[str] = set()
        self.last_activity = time.monotonic()
        self.started_at = time.monotonic()

        # What the *speakers* are doing, as reported by the browser. Distinct
        # from `state`, and the distinction is the whole reason the assistant
        # stops hearing itself — see `set_client_playback`.
        self._client_playing = False
        self._playback_ended_at = 0.0

    # ── transitions ─────────────────────────────────────────────────────────

    def begin_turn(self, context_id: str) -> None:
        """A new utterance is starting."""
        self.context_id = context_id
        self.state = TurnState.LISTENING
        self._consecutive = 0
        self.last_activity = time.monotonic()

    def begin_thinking(self, context_id: str) -> None:
        self.context_id = context_id
        self.state = TurnState.THINKING
        self.last_activity = time.monotonic()

    def begin_speaking(self, context_id: str) -> None:
        # Only stamp the clock on the transition into SPEAKING. Re-stamping on
        # every sentence would restart the grace period mid-answer and make a
        # long answer progressively harder to interrupt.
        if self.state is not TurnState.SPEAKING:
            self._speaking_since = time.monotonic()
            self._consecutive = 0
        self.context_id = context_id
        self.state = TurnState.SPEAKING
        self.last_activity = time.monotonic()

    def finish(self) -> None:
        self.state = TurnState.IDLE
        self._consecutive = 0
        self._speaking_since = 0.0
        self.last_activity = time.monotonic()

    # ── what the speakers are doing ─────────────────────────────────────────

    def set_client_playback(self, active: bool) -> None:
        """The browser reporting whether its speakers are producing sound.

        This is the only honest answer to "is the assistant talking *right
        now*", and having it is the difference between a voice agent that works
        and one that answers itself.

        The server knows when it finished *sending* audio. That is not when the
        officer stops hearing it: synthesis is streamed ahead of playback, so
        several seconds of speech can still be queued in the browser when the
        last packet leaves. `TurnState.SPEAKING` therefore ends early — and for
        the whole remainder of the answer the microphone would be open to a
        room containing the assistant's own voice. That is precisely the window
        in which it transcribes itself and replies to its reply.

        The failure is worse with client-side synthesis, where the server sends
        text and never sees audio at all: `SPEAKING` lasts milliseconds while
        the browser talks for ten seconds.

        So playback state is reported by the only component that can know it,
        and it — not the turn state — gates the microphone.
        """
        now = time.monotonic()
        if active and not self._client_playing:
            # Start the interruption grace period when the audio becomes
            # audible, not when synthesis began. It is playback an officer
            # talks over, and the two can be a second apart.
            self._speaking_since = now
            self._consecutive = 0
        elif self._client_playing and not active:
            self._playback_ended_at = now
        self._client_playing = active
        self.last_activity = now

    @property
    def output_active(self) -> bool:
        """True while the assistant's voice is, or has just been, in the room."""
        if self._client_playing:
            return True
        if (self._playback_ended_at
                and time.monotonic() - self._playback_ended_at
                < PLAYBACK_HANGOVER_SECONDS):
            return True
        # No report from this client — fall back to the turn state, which is
        # right for a non-browser client and never worse than the old
        # behaviour for one that simply has not reported yet.
        return self.state is TurnState.SPEAKING

    # ── interruption ────────────────────────────────────────────────────────

    @property
    def suppress_microphone(self) -> bool:
        """True while the assistant's own voice would be arriving.

        The session drops these frames before the recogniser, which is what
        stops the assistant transcribing itself. The VAD still sees them —
        interruption detection needs them, and it applies its own stricter
        threshold below.
        """
        return self.output_active

    def observe_speech(self, is_speech: bool, probability: float) -> bool:
        """Feed one VAD verdict. True means: interrupt now.

        Returns True at most once per turn. The caller acts on it and the
        machine leaves SPEAKING, so a sustained interruption cannot fire
        repeatedly and cancel the turn that replaced it.
        """
        if not self.output_active:
            self._consecutive = 0
            return False

        # Once a turn has been abandoned it cannot be abandoned again. The
        # latch used to be implicit — firing left SPEAKING, and SPEAKING was
        # the only state this ran in — but the microphone now stays gated
        # through the playback tail, and the officer who just interrupted is
        # still talking. Without this they interrupt three more times a second.
        if self.is_stale(self.context_id):
            self._consecutive = 0
            return False

        if time.monotonic() - self._speaking_since < self._grace:
            return False

        if not is_speech or probability < self._probability:
            self._consecutive = 0
            return False

        self._consecutive += 1
        if self._consecutive < self._required_frames:
            return False

        log.info("barge-in after %d frames (p=%.2f) — cancelling turn %s",
                 self._consecutive, probability, self.context_id)
        self._consecutive = 0
        self.mark_interrupted(self.context_id)
        self.state = TurnState.IDLE
        # Acting on an interruption stops playback at the client. Assume it,
        # rather than waiting for the report that says so — but keep the
        # hangover, because the samples already in the speakers still play.
        if self._client_playing:
            self._client_playing = False
            self._playback_ended_at = time.monotonic()
        self.last_activity = time.monotonic()
        return True

    def mark_interrupted(self, context_id: str) -> None:
        if context_id:
            self._interrupted_contexts.add(context_id)
            # Only the recent past matters — anything older cannot still have
            # audio in flight, and the set should not grow for the life of a
            # session that may run all shift.
            if len(self._interrupted_contexts) > 32:
                self._interrupted_contexts = set(
                    list(self._interrupted_contexts)[-16:])

    def is_stale(self, context_id: str) -> bool:
        """True for a packet belonging to a turn that was abandoned.

        Checked at the top of every handler. Synthesis and LLM generation are
        both in flight when an interruption lands, and both will keep producing
        packets for a moment afterwards; this is what stops the previous
        answer's second half playing over the new question.
        """
        return context_id in self._interrupted_contexts

    # ── idling ──────────────────────────────────────────────────────────────

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_activity

    def session_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def snapshot(self) -> dict:
        return {"state": self.state.value, "context_id": self.context_id,
                "speakers_live": self._client_playing,
                "microphone_gated": self.suppress_microphone,
                "idle_seconds": round(self.idle_seconds(), 1),
                "session_seconds": round(self.session_seconds(), 1)}
