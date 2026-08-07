"""Numbers → the words a person would actually say.

Ported from Rapida's `number_to_word_normalizer.go`, with the numbering system
changed. Rapida spells 150000 as "one hundred fifty thousand"; in India that
number is spoken "one lakh fifty thousand", it is written 1,50,000 with the
grouping that implies, and an assistant used by Gujarat Police that says the
Western form sounds foreign in a way that undermines it.

So this implements the Indian system — thousand, lakh, crore, with two-digit
grouping above the thousand — and understands both `1,50,000` and `150,000` on
input, because analysts type both.

Three things here are less obvious than the arithmetic:

  *Years are not counted.* 2026 is "twenty twenty-six", not "two thousand and
  twenty-six". Speaking a date the long way is instantly recognisable as a
  machine.

  *Decimals are digits after the point.* 67.4 is "sixty-seven point four", not
  "sixty-seven point four tenths". This matters because every threat score in
  the product has one decimal place.

  *Big numbers stay approximate when they are approximate.* A count of 1,247
  posts is read "one thousand two hundred forty-seven"; that is correct and it
  is also a mouthful. The caller decides via `spell_exact`, because "about
  twelve hundred" is right for a briefing and wrong for evidence.
"""
from __future__ import annotations

import re

_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
          "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]

_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]

_ORDINALS = {
    1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth",
    9: "ninth", 12: "twelfth",
}


def _under_hundred(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    tens, unit = divmod(n, 10)
    return _TENS[tens] + (f"-{_UNITS[unit]}" if unit else "")


def _under_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts: list[str] = []
    if hundreds:
        parts.append(f"{_UNITS[hundreds]} hundred")
    if rest:
        # "and" after hundreds is how the number is said aloud here, and its
        # absence is one of the tells that a machine is reading.
        parts.append(("and " if hundreds else "") + _under_hundred(rest))
    return " ".join(parts)


def integer_to_words(value: int) -> str:
    """Spell an integer using the Indian numbering system."""
    if value < 0:
        return "minus " + integer_to_words(-value)
    if value < 1000:
        return _under_thousand(value) or "zero"

    parts: list[str] = []
    crore, value = divmod(value, 10_000_000)
    if crore:
        parts.append(f"{integer_to_words(crore)} crore")
    lakh, value = divmod(value, 100_000)
    if lakh:
        parts.append(f"{_under_hundred(lakh)} lakh")
    thousand, value = divmod(value, 1000)
    if thousand:
        parts.append(f"{_under_hundred(thousand)} thousand")
    if value:
        parts.append(_under_thousand(value))
    return " ".join(parts)


def year_to_words(year: int) -> str:
    """1947 → "nineteen forty-seven"; 2026 → "twenty twenty-six".

    The 2000-2009 range is the exception — "twenty oh five" is regional, and
    "two thousand five" is what everyone says.
    """
    if not 1000 <= year <= 2999:
        return integer_to_words(year)
    if 2000 <= year <= 2009:
        return "two thousand" + (f" {_UNITS[year - 2000]}" if year > 2000 else "")
    high, low = divmod(year, 100)
    if low == 0:
        return f"{_under_hundred(high)} hundred"
    return f"{_under_hundred(high)} {_under_hundred(low)}"


def decimal_to_words(text: str) -> str:
    """"67.4" → "sixty-seven point four"."""
    whole, _, fraction = text.partition(".")
    spoken = integer_to_words(int(whole or 0))
    if not fraction:
        return spoken
    digits = " ".join(_UNITS[int(d)] for d in fraction if d.isdigit())
    return f"{spoken} point {digits}" if digits else spoken


def ordinal_to_words(value: int) -> str:
    if value in _ORDINALS:
        return _ORDINALS[value]
    words = integer_to_words(value)
    last = words.split("-")[-1].split(" ")[-1]
    for number, ordinal in _ORDINALS.items():
        if last == _UNITS[number]:
            return words[: -len(last)] + ordinal
    if last.endswith("y"):
        return words[:-1] + "ieth"
    return words + "th"


# ── the normalizer ──────────────────────────────────────────────────────────

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_ORDINAL_RANGE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s*[-–]\s*(\d+)(?:st|nd|rd|th)\b",
                            re.IGNORECASE)
_ORDINAL = re.compile(r"\b(\d+)(st|nd|rd|th)\b", re.IGNORECASE)
# Statute sections — IPC 153A, CrPC 41A. Said "one fifty-three A", and left as
# digits a synthesiser runs the number into the letter. Common enough in this
# product's output to be worth its own rule.
_SECTION = re.compile(r"\b(\d{1,4})([A-Z])\b")
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_RANGE = re.compile(r"\b(\d+)\s*[-–]\s*(\d+)\b")
_DECIMAL = re.compile(r"\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b")
_SCORE = re.compile(r"\b(\d+(?:\.\d+)?)\s*/\s*(\d+)\b")


class NumberNormalizer:
    """Rewrites every numeric form in a sentence into spoken words."""

    name = "number"

    def normalize(self, text: str) -> str:
        # Order matters throughout: each pattern consumes the digits a later
        # one would otherwise mangle. Scores before ranges before years before
        # bare numbers.
        text = _SCORE.sub(
            lambda m: f"{decimal_to_words(m.group(1))} out of "
                      f"{integer_to_words(int(m.group(2)))}", text)
        text = _PERCENT.sub(lambda m: f"{decimal_to_words(m.group(1))} percent", text)
        text = _SECTION.sub(
            lambda m: f"{integer_to_words(int(m.group(1)))} {m.group(2)}", text)
        # Ordinal ranges before bare ordinals, or "3rd-5th" loses its hyphen to
        # the ordinal pass and becomes "third-fifth" rather than "third to fifth".
        text = _ORDINAL_RANGE.sub(
            lambda m: f"{ordinal_to_words(int(m.group(1)))} to "
                      f"{ordinal_to_words(int(m.group(2)))}", text)
        text = _ORDINAL.sub(lambda m: ordinal_to_words(int(m.group(1))), text)
        text = _RANGE.sub(
            lambda m: f"{integer_to_words(int(m.group(1)))} to "
                      f"{integer_to_words(int(m.group(2)))}", text)
        text = _YEAR.sub(lambda m: year_to_words(int(m.group(1))), text)

        def _plain(match: re.Match) -> str:
            raw = match.group(0).replace(",", "")
            try:
                return decimal_to_words(raw) if "." in raw \
                    else integer_to_words(int(raw))
            except ValueError:
                return match.group(0)

        return _DECIMAL.sub(_plain, text)
