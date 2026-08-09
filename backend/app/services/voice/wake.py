"""Wake word — deciding which speech in the room was addressed to Sentinel.

The microphone is open from sign-in. That is the right design for a console an
officer talks to with their hands on a map, and it has one consequence nobody
enjoys: a control room is *full* of speech, almost none of it aimed at the
assistant. Two officers discussing a Rajkot thread, a phone call, a briefing at
the next desk — an always-listening assistant answers all of it, out loud, over
the top of the people talking. The failure is not that it mishears; it is that
it hears correctly and replies anyway.

So recognition stays always-on and *addressing* becomes the gate. Only speech
that names Sentinel opens a turn.

**Why the transcript and not an audio keyword spotter.** The obvious build is
openWakeWord or Porcupine on the raw frames. This deployment already runs
Whisper on every utterance, so the name is already in a string by the time any
decision has to be made — a second model would add a download, a per-frame
inference budget and its own false-accept rate to learn nothing new. It would
also be worse at the job: keyword spotters are trained per-phrase on English
and this room code-switches mid-sentence, while Whisper transcribes "સેન્ટિનલ,
બ્રીફ મી" as readily as the English. The audio route wins when there is no
transcript to read (battery-powered, always-off DSP wake-up). Here there always
is one.

**The follow-up window is what makes it usable.** Requiring the name on every
sentence is correct and exhausting — real conversation is "Sentinel, brief me
on Surat" / "and Rajkot?" / "who posted that?", and a gate that drops the
second and third questions is worse than no gate. So an answer opens a window
during which the officer is simply still talking to Sentinel. Speaking again
extends it. The gate closes on silence, which is exactly when the officer has
turned back to the room.

**Mishearing is designed around, not hoped away.** Whisper does not reliably
return "Sentinel" — it returns "sentinal", "centennial", "sent in all", "st
enel" and a dozen other things, most often from a non-native speaker, which
here is nearly everyone. A gate that only accepted the correct spelling would
be a gate that mostly ignores the officer, and "it doesn't listen to me" is how
a feature gets switched off for good. VARIANTS is therefore deliberately
loose. The asymmetry justifies it: a false accept costs one unwanted answer
that the officer talks over, while a false reject costs the whole feature's
credibility.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata

from app.config import settings

log = logging.getLogger("sentinel.voice.wake")

#: How the name comes back from a recogniser listening to Gujarati-accented
#: English across a room. Every one of these was cheaper to accept than to
#: explain to an officer whose console ignored them.
#:
#: Indic spellings are included because an officer speaking Gujarati or Hindi
#: says the name in that sentence's script, and dropping those would make the
#: gate an English-only feature in a bilingual room.
VARIANTS = frozenset({
    "sentinel", "sentinal", "sentinell", "sentinelle", "sentnel", "sentinl",
    "centinel", "centinal", "centennial", "sentenial", "sentimental",
    "santinel", "santinal", "sentin", "sentry",
    "rakshak", "erakshak", "e rakshak", "rakshakji",
    "सेंटिनल", "सेण्टिनल", "सेंटीनल", "સેન્ટિનલ", "સેંટિનલ",
    "रक्षक", "ई रक्षक", "ईरक्षक", "રક્ષક", "ઈ રક્ષક", "ઈરક્ષક",
})

#: Two-token hearings of the one name. Checked before the single-token pass,
#: because "sent in all" is three tokens that mean "Sentinel" and no amount of
#: per-word matching finds it.
SPLIT_VARIANTS = ("sent in all", "sent in el", "sent in nel", "send in el",
                  "cent in el", "sent i nel", "set in el",
                  "e rakshak", "e rakshaq", "he rakshak")

#: Optional politeness in front of the name, in the languages this room uses.
PREFIXES = frozenset({"hey", "hi", "hello", "ok", "okay", "yo", "oi",
                      "are", "अरे", "हे", "ઓ", "અરે"})

#: How far into the utterance the name may appear. Addressing something happens
#: at the start of a sentence; "the sentinel dashboard shows" is a sentence
#: *about* the console, not one aimed at it, and it is not a summons.
MAX_PREFIX_TOKENS = 3

#: Combining marks that are part of a *word*, not decoration on one.
#:
#: `\w` is Unicode-aware but only for letters and digits (L*/N*), and every
#: Indic vowel sign, anusvara and virama is a mark (M*). A plain `[^\w\s]`
#: strip therefore shreds "સેન્ટિનલ" into disconnected consonants — which is
#: precisely how the Gujarati and Hindi spellings of the name below failed to
#: match themselves. The Instagram adapter's hashtag regex carries the same
#: ranges for the same reason; this is that lesson, in the other half of the
#: product.
_MARKS = ("ऀ-ःऺ-ॏ॑-ॗॢ-ॣ"  # Devanagari
          "ઁ-ઃ઼-્ૢ-ૣ"              # Gujarati
          "‌‍")                                        # ZWNJ / ZWJ

_PUNCTUATION = re.compile(rf"[^\w\s{_MARKS}]", re.UNICODE)

#: Combining diacriticals in the Latin range only — the accents on "Séntinel".
_LATIN_ACCENTS = re.compile(r"[̀-ͯ]")


def _normalise(text: str) -> str:
    """Casefold, drop Latin accents and punctuation, collapse whitespace.

    Only *Latin* accents are removed. Decomposing and stripping every
    combining mark is the obvious implementation and it is wrong here: it
    deletes the virama and every matra, so the Devanagari and Gujarati
    spellings of the name reduce to bare consonant strings that no longer match
    the entries they were written as. Latin accents are decoration; an Indic
    matra is a vowel.
    """
    decomposed = unicodedata.normalize("NFKD", text or "").casefold()
    unaccented = unicodedata.normalize("NFC", _LATIN_ACCENTS.sub("", decomposed))
    return " ".join(_PUNCTUATION.sub(" ", unaccented).split())


class WakeWord:
    """The gate. One per session; not thread-safe and does not need to be.

    Holds only the follow-up deadline, so an officer who reconnects mid-shift
    starts a fresh conversation rather than inheriting an open window from a
    session that ended ten minutes ago.
    """

    def __init__(self, *, enabled: bool | None = None,
                 follow_up_seconds: float | None = None) -> None:
        self.enabled = (settings.VOICE_WAKE_WORD_ENABLED
                        if enabled is None else enabled)
        self.follow_up_seconds = (settings.VOICE_WAKE_FOLLOW_UP_SECONDS
                                  if follow_up_seconds is None else follow_up_seconds)
        self._open_until = 0.0

    # ── the window ──────────────────────────────────────────────────────────

    def open_follow_up(self) -> None:
        """Called when Sentinel finishes speaking. The officer is now mid
        conversation and should not have to say the name again."""
        self._open_until = time.monotonic() + self.follow_up_seconds

    def close(self) -> None:
        """Drop back to requiring the name — used when a turn is abandoned."""
        self._open_until = 0.0

    @property
    def listening(self) -> bool:
        return time.monotonic() < self._open_until

    @property
    def expires_in(self) -> float:
        """Seconds of window left, for the client's own countdown."""
        return max(0.0, self._open_until - time.monotonic())

    # ── the decision ────────────────────────────────────────────────────────

    def strip(self, text: str) -> str | None:
        """The question with the name removed, or None if it was not addressed.

        An empty string is a meaningful third answer and not the same as None:
        the officer said "Sentinel" and nothing else. That is an address
        without a question, so it opens the window and asks nothing — the next
        sentence lands as a follow-up. It is also how someone naturally starts
        when they have not decided what to ask yet.
        """
        # Raw word paired with its normalised form, so that dropping the wake
        # phrase can be done by position and the *original* words returned.
        # Matching on normalised text but slicing the raw string by the same
        # index is the subtle way to get this wrong: "Sentinel,brief" is one
        # raw token and two normalised ones, and every index after it is off
        # by one — which silently eats the first word of the question.
        pairs = [(raw, _normalise(raw)) for raw in text.split()]
        pairs = [(raw, norm) for raw, norm in pairs if norm]  # drop bare punctuation
        if not pairs:
            return None

        def tail(skip: int) -> str:
            """The question, in its original script and casing — the assistant
            needs the proper nouns that casefolding would flatten."""
            return " ".join(raw for raw, _norm in pairs[skip:])

        # Multi-token hearings first: "sent in all" is three tokens that mean
        # one name, and no per-token pass will ever find it.
        head = " ".join(norm for _raw, norm in pairs[:MAX_PREFIX_TOKENS + 2])
        for variant in SPLIT_VARIANTS:
            position = head.find(variant)
            if position == -1 or (position and head[position - 1] != " "):
                continue
            # Tokens consumed = words before the match, plus the match itself.
            consumed = len(head[:position].split()) + len(variant.split())
            return tail(consumed)

        for index, (_raw, norm) in enumerate(pairs[:MAX_PREFIX_TOKENS]):
            first = norm.split()[0]
            if first in VARIANTS:
                # A token that normalised into several words ("Sentinel,brief")
                # keeps everything after the name.
                rest = norm.split()[1:]
                return " ".join(rest + [tail(index + 1)]).strip()
            if first not in PREFIXES:
                # A real word that is neither the name nor a politeness token:
                # the officer is talking about something else and the sentence
                # has already moved on.
                return None
        return None

    def admit(self, text: str, *, spoken: bool) -> str | None:
        """The whole policy in one call.

        Returns the text to act on, or None to ignore this utterance.

        Typed input is never gated. Someone who clicked into the console's own
        input box and typed has addressed it about as unambiguously as it is
        possible to do, and making them type "Sentinel," first would be a
        gate protecting against nothing.
        """
        if not self.enabled or not spoken:
            return text

        if self.listening:
            # Mid-conversation. Extend the window rather than merely honouring
            # it: a run of follow-ups should not time out at a fixed distance
            # from the first answer.
            self.open_follow_up()
            return text

        stripped = self.strip(text)
        if stripped is None:
            log.debug("wake: ignored unaddressed speech (%d chars)", len(text))
            return None

        self.open_follow_up()
        if not stripped.strip():
            log.debug("wake: addressed with no question — window open")
            return ""
        return stripped
