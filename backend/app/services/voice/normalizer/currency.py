"""Currency and units → spoken form.

Ported from Rapida's `currency_normalizer.go`, re-centred on the rupee. "₹50,000"
must become "fifty thousand rupees" and not "rupee five zero comma zero zero
zero", which is what an unnormalised TTS engine produces when it meets a symbol
it does not have a rule for.

Runs before `NumberNormalizer`, because it has to see the digits still as
digits to attach the right unit to them. The pipeline in `__init__.py` fixes
that order and it is not arbitrary.
"""
from __future__ import annotations

import re

from app.services.voice.normalizer.number import decimal_to_words, integer_to_words

# Symbol → (singular, plural). Plural matters: "one rupee", "fifty rupees".
_SYMBOLS: dict[str, tuple[str, str]] = {
    "₹": ("rupee", "rupees"),
    "$": ("dollar", "dollars"),
    "€": ("euro", "euros"),
    "£": ("pound", "pounds"),
    "¥": ("yen", "yen"),
}

# Written forms that mean the same thing.
_CODES: dict[str, tuple[str, str]] = {
    "rs": ("rupee", "rupees"),
    "rs.": ("rupee", "rupees"),
    "inr": ("rupee", "rupees"),
    "usd": ("dollar", "dollars"),
    "eur": ("euro", "euros"),
    "gbp": ("pound", "pounds"),
}

# Indian magnitude words attach to the amount, not the currency: "two crore
# rupees", never "two rupees crore".
_MAGNITUDES = {
    "k": "thousand", "l": "lakh", "lakh": "lakh", "lakhs": "lakh",
    "cr": "crore", "crore": "crore", "crores": "crore",
    "m": "million", "mn": "million", "bn": "billion",
}

_AMOUNT = r"(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
_MAGNITUDE = r"(?:\s*(k|l|lakhs?|cr|crores?|m|mn|bn))?"

_SYMBOL_FIRST = re.compile(
    r"([₹$€£¥])\s*" + _AMOUNT + _MAGNITUDE, re.IGNORECASE)
_CODE_FIRST = re.compile(
    r"\b(rs\.?|inr|usd|eur|gbp)\s*" + _AMOUNT + _MAGNITUDE, re.IGNORECASE)
_AMOUNT_FIRST = re.compile(
    _AMOUNT + _MAGNITUDE + r"\s*([₹$€£¥])", re.IGNORECASE)


def _spell_amount(raw: str) -> tuple[str, bool]:
    """`(words, is_singular)` for the numeric part."""
    cleaned = raw.replace(",", "")
    try:
        if "." in cleaned:
            return decimal_to_words(cleaned), float(cleaned) == 1.0
        value = int(cleaned)
        return integer_to_words(value), value == 1
    except ValueError:
        return raw, False


def _render(amount: str, magnitude: str | None,
            unit: tuple[str, str]) -> str:
    words, singular = _spell_amount(amount)
    if magnitude:
        scale = _MAGNITUDES.get(magnitude.lower())
        if scale:
            words = f"{words} {scale}"
            singular = False        # "one lakh rupees", never "rupee"
    return f"{words} {unit[0] if singular else unit[1]}"


class CurrencyNormalizer:
    name = "currency"

    def normalize(self, text: str) -> str:
        text = _SYMBOL_FIRST.sub(
            lambda m: _render(m.group(2), m.group(3), _SYMBOLS[m.group(1)]), text)
        text = _CODE_FIRST.sub(
            lambda m: _render(m.group(2), m.group(3),
                              _CODES[m.group(1).lower()]), text)
        text = _AMOUNT_FIRST.sub(
            lambda m: _render(m.group(1), m.group(2), _SYMBOLS[m.group(3)]), text)
        return text


# ── measurement units ───────────────────────────────────────────────────────

# Kept separate from currency because they are a different failure: a TTS
# engine reads "km" as "kay em" rather than getting it wrong in an interesting
# way, and the fix is a straight substitution.
_UNITS: dict[str, tuple[str, str]] = {
    "km": ("kilometre", "kilometres"),
    "kms": ("kilometre", "kilometres"),
    "m": ("metre", "metres"),
    "cm": ("centimetre", "centimetres"),
    "kg": ("kilogram", "kilograms"),
    "g": ("gram", "grams"),
    "hr": ("hour", "hours"),
    "hrs": ("hour", "hours"),
    "min": ("minute", "minutes"),
    "mins": ("minute", "minutes"),
    "sec": ("second", "seconds"),
    "secs": ("second", "seconds"),
    "ms": ("millisecond", "milliseconds"),
}

_UNIT_PATTERN = re.compile(
    r"\b" + _AMOUNT + r"\s*(" + "|".join(sorted(_UNITS, key=len, reverse=True))
    + r")\b")


class UnitNormalizer:
    name = "unit"

    def normalize(self, text: str) -> str:
        def _replace(match: re.Match) -> str:
            words, singular = _spell_amount(match.group(1))
            singular_form, plural = _UNITS[match.group(2).lower()]
            return f"{words} {singular_form if singular else plural}"

        return _UNIT_PATTERN.sub(_replace, text)
