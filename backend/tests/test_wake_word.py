"""Addressing: which speech in the room was meant for Sentinel.

The microphone is open from sign-in, so the assistant hears a control room's
entire working day — two officers arguing about a Rajkot thread, a phone call,
a shift briefing at the next desk. Without a gate it answers all of it, aloud,
over the people talking.

Both directions of failure are tested here because they fail differently:

  * a **false accept** costs one unwanted answer the officer talks over, and
  * a **false reject** costs the feature — "it never listens to me" is how
    this gets turned off for the rest of the deployment.

Which is why the matcher is deliberately loose about spelling and strict about
position. Whisper returns the name half a dozen ways from a Gujarati-accented
speaker; but a name three words into a sentence is a sentence *about* the
console, not one aimed at it.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import pytest

from app.services.voice.wake import VARIANTS, WakeWord, _normalise


@pytest.fixture
def gate() -> WakeWord:
    return WakeWord(enabled=True, follow_up_seconds=20.0)


# --- being addressed -------------------------------------------------------

@pytest.mark.parametrize("spoken, question", [
    ("Sentinel, brief me on Surat.", "brief me on Surat."),
    ("sentinel brief me on surat", "brief me on surat"),
    ("Hey Sentinel, what's the threat score?", "what's the threat score?"),
    ("OK Sentinel, critical alerts please", "critical alerts please"),
    ("Okay sentinel show me the watchlist", "show me the watchlist"),
    # No space after the comma — one raw token, two normalised ones. Slicing
    # the raw string by a normalised index eats the first word of the question.
    ("Sentinel,brief me now", "brief me now"),
])
def test_a_question_addressed_to_sentinel_loses_only_the_name(gate, spoken, question):
    assert gate.strip(spoken) == question


@pytest.mark.parametrize("misheard", [
    "Sentinal, brief me", "Centinel, brief me", "Centennial, brief me",
    "Sentimental, brief me", "Santinel, brief me", "Séntinel, brief me",
    # Heard as several words. No per-token pass finds this one.
    "Sent in all, brief me", "sent in el brief me",
])
def test_the_name_is_recognised_however_whisper_mangles_it(gate, misheard):
    """Every one of these is a real hearing of the name from an accented
    speaker. Accepting them is cheaper than explaining to an officer why the
    console ignores them."""
    assert gate.strip(misheard) == "brief me"


def test_the_name_is_recognised_in_the_scripts_the_room_speaks(gate):
    """An officer speaking Gujarati says the name in that sentence's script.
    Dropping these would make the wake word an English-only feature in a
    bilingual control room — and the question must come back in its original
    script, not a punctuation-stripped shadow of it."""
    assert gate.strip("સેન્ટિનલ, રાજકોટ બતાવો") == "રાજકોટ બતાવો"
    assert gate.strip("सेंटिनल, सूरत का हाल बताओ") == "सूरत का हाल बताओ"


def test_every_spelling_of_the_name_survives_normalisation():
    """The regression that made the Indic spellings dead entries.

    `\\w` is Unicode-aware for letters and digits only, so a plain `[^\\w\\s]`
    strip deletes every matra, anusvara and virama — and "સેન્ટિનલ" stops
    matching the very constant it was written into.
    """
    for variant in VARIANTS:
        assert _normalise(variant) == variant


def test_the_question_keeps_its_original_casing_and_script(gate):
    """Matching happens on a casefolded string; what reaches the assistant must
    not be. Flattening it costs every proper noun in the sentence."""
    assert gate.strip("Sentinel, how is Vadodara?") == "how is Vadodara?"


# --- not being addressed ---------------------------------------------------

@pytest.mark.parametrize("chatter", [
    "did you see that Rajkot thread",
    "so I told him the score was 67.4 and he just laughed",
    "hey can you pass me that file",
    "no the other one, the Ahmedabad case",
    "",
    "   ",
])
def test_room_conversation_is_ignored(gate, chatter):
    assert gate.strip(chatter) is None


@pytest.mark.parametrize("about_it", [
    "The sentinel dashboard shows four alerts",
    "I checked it on sentinel earlier and it was fine",
    "we should get sentinel to do that",
])
def test_talking_about_the_console_is_not_talking_to_it(gate, about_it):
    """Position is the whole signal. Addressing happens at the start of a
    sentence; the name buried mid-clause is a noun, not a summons."""
    assert gate.strip(about_it) is None


# --- the follow-up window --------------------------------------------------

def test_a_follow_up_needs_no_wake_word(gate):
    """Requiring the name every sentence is correct and exhausting. Real use is
    "Sentinel, brief me on Surat" / "and Rajkot?" / "who posted it?" — a gate
    that drops the second and third questions is worse than no gate."""
    assert gate.admit("and Rajkot?", spoken=True) is None      # cold
    assert gate.admit("Sentinel, brief me", spoken=True) == "brief me"
    assert gate.admit("and Rajkot?", spoken=True) == "and Rajkot?"
    assert gate.admit("who posted it?", spoken=True) == "who posted it?"


def test_the_window_closes_on_silence(gate):
    """It closes when the officer stops talking, which is exactly when they
    have turned back to the room."""
    gate.admit("Sentinel, brief me", spoken=True)
    assert gate.listening
    gate.follow_up_seconds = 0.0
    gate.open_follow_up()
    assert not gate.listening
    assert gate.admit("pass me that file", spoken=True) is None


def test_each_follow_up_extends_the_window(gate):
    """A run of follow-ups must not time out at a fixed distance from the first
    answer — the conversation is still going."""
    gate.admit("Sentinel, brief me", spoken=True)
    first = gate._open_until
    gate.admit("and Rajkot?", spoken=True)
    assert gate._open_until >= first


def test_answering_opens_the_window(gate):
    """The session calls this when synthesis finishes. Without it the officer
    would have to name Sentinel again immediately after being answered."""
    assert not gate.listening
    gate.open_follow_up()
    assert gate.listening


def test_the_name_alone_opens_the_window_and_asks_nothing(gate):
    """"Sentinel." is an address without a question — which is how someone
    starts when they have not finished deciding what to ask. Empty string, not
    None: the difference is that this one opens the window."""
    assert gate.admit("Sentinel.", spoken=True) == ""
    assert gate.listening
    assert gate.admit("brief me on Surat", spoken=True) == "brief me on Surat"


# --- what the gate must never block ----------------------------------------

def test_typing_is_never_gated(gate):
    """Clicking into the console's input box and typing is about as
    unambiguous as addressing gets. Making an officer type "Sentinel," first
    would be a gate protecting against nothing."""
    assert gate.admit("brief me on Surat", spoken=False) == "brief me on Surat"
    assert not gate.listening      # and typing does not open a voice window


def test_disabling_the_gate_lets_everything_through():
    """A single-operator desk has no room conversation to filter, and the
    setting has to actually mean off."""
    off = WakeWord(enabled=False)
    assert off.admit("brief me on Surat", spoken=True) == "brief me on Surat"


def test_a_new_session_does_not_inherit_an_open_window():
    """The window is per session, so an officer reconnecting after a dropped
    network starts a fresh conversation rather than one the previous session
    left open."""
    first = WakeWord(enabled=True)
    first.open_follow_up()
    assert not WakeWord(enabled=True).listening
