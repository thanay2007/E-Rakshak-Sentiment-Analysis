"""Dates, times and durations → spoken form.

Ported from Rapida's `date_normalizer.go` and `time_normalizer.go`.

The one decision worth stating: **dates are read day-first.** 03/04/2026 is the
third of April here, not the fourth of March, and getting that backwards in a
police tool is not a cosmetic error — it changes when an officer believes
something happened. Where a string is genuinely ambiguous this reads it
day-first and does not hedge, because ISO input (2026-04-03) is unambiguous and
handled separately, and every locale-aware guess is worse than one stated
convention.

Durations get their own pass because the assistant produces them constantly
("in the last 168 hours") and "one hundred sixty-eight hours" is a worse answer
than "the last seven days" even though both are true.
"""
from __future__ import annotations

import re

from app.services.voice.normalizer.number import (integer_to_words,
                                                  ordinal_to_words, year_to_words)

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]

_MONTH_BY_NAME = {name.lower()[:3]: i + 1 for i, name in enumerate(_MONTHS)}

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?")
_SLASHED = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b")
_24H = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\b")
_12H = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?\s*m\.?\b",
                  re.IGNORECASE)


def _spoken_date(day: int, month: int, year: int | None) -> str:
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return ""
    spoken = f"the {ordinal_to_words(day)} of {_MONTHS[month - 1]}"
    return f"{spoken} {year_to_words(year)}" if year else spoken


def _spoken_clock(hour: int, minute: int) -> str:
    """A 24-hour clock read the way it is spoken, not the way it is written.

    14:30 is "half past two in the afternoon". The period suffix is what stops
    an alert timestamp being ambiguous when it is heard rather than seen.
    """
    period = ("in the morning" if hour < 12 else
              "in the afternoon" if hour < 17 else
              "in the evening" if hour < 21 else "at night")
    display_hour = hour % 12 or 12
    hour_words = integer_to_words(display_hour)

    if minute == 0:
        return f"{hour_words} o'clock {period}"
    if minute == 15:
        return f"quarter past {hour_words} {period}"
    if minute == 30:
        return f"half past {hour_words} {period}"
    if minute == 45:
        next_hour = integer_to_words((display_hour % 12) + 1)
        return f"quarter to {next_hour} {period}"
    # "oh five" rather than "five" for single digits, which is how a time is
    # read aloud and how it is distinguished from the hour.
    minute_words = (f"oh {integer_to_words(minute)}" if minute < 10
                    else integer_to_words(minute))
    return f"{hour_words} {minute_words} {period}"


class DateNormalizer:
    name = "date"

    def normalize(self, text: str) -> str:
        def _iso(match: re.Match) -> str:
            year, month, day = (int(match.group(i)) for i in (1, 2, 3))
            spoken = _spoken_date(day, month, year)
            if not spoken:
                return match.group(0)
            if match.group(4) is not None:
                spoken += " at " + _spoken_clock(int(match.group(4)),
                                                 int(match.group(5)))
            return spoken

        def _slashed(match: re.Match) -> str:
            day, month = int(match.group(1)), int(match.group(2))
            year = int(match.group(3))
            if year < 100:
                year += 2000 if year < 70 else 1900
            return _spoken_date(day, month, year) or match.group(0)

        return _SLASHED.sub(_slashed, _ISO.sub(_iso, text))


class TimeNormalizer:
    name = "time"

    def normalize(self, text: str) -> str:
        def _twelve(match: re.Match) -> str:
            hour = int(match.group(1)) % 12
            minute = int(match.group(2) or 0)
            if match.group(3).lower() == "p":
                hour += 12
            return _spoken_clock(hour, minute)

        def _twenty_four(match: re.Match) -> str:
            return _spoken_clock(int(match.group(1)), int(match.group(2)))

        # 12-hour first: "3:30 pm" would otherwise be consumed by the 24-hour
        # pattern and lose its meridiem.
        return _24H.sub(_twenty_four, _12H.sub(_twelve, text))


# ── durations ───────────────────────────────────────────────────────────────

_DURATION = re.compile(
    r"\b(\d+)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?|days?|weeks?)\b",
    re.IGNORECASE)


class DurationNormalizer:
    """Says a duration the way a person would.

    168 hours becomes "seven days" and 24 hours becomes "twenty-four hours"
    rather than "one day", because "the last 24 hours" is the fixed phrase
    everyone in an operations room uses and rewriting it would sound wrong.
    """

    name = "duration"

    def normalize(self, text: str) -> str:
        def _replace(match: re.Match) -> str:
            amount, unit = int(match.group(1)), match.group(2).lower()
            if unit.startswith(("hour", "hr")):
                if amount == 168:
                    return "seven days"
                if amount == 720:
                    return "thirty days"
                if amount and amount % 24 == 0 and amount > 48:
                    days = amount // 24
                    return f"{integer_to_words(days)} day{'' if days == 1 else 's'}"
                unit_word = "hour"
            elif unit.startswith(("min",)):
                unit_word = "minute"
            elif unit.startswith(("sec",)):
                unit_word = "second"
            elif unit.startswith("day"):
                unit_word = "day"
            else:
                unit_word = "week"
            plural = "" if amount == 1 else "s"
            return f"{integer_to_words(amount)} {unit_word}{plural}"

        return _DURATION.sub(_replace, text)
