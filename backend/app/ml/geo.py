# -*- coding: utf-8 -*-
"""City geo-tagging for live-platform posts.

Simulated posts carry their city; posts from real APIs usually don't. When a
collector didn't already geo-tag a post (seed page/subreddit :City suffix),
infer the city from mentions in the text — covering English, Hindi and
Gujarati spellings of the deployment's target cities.
"""
import unicodedata

from app.data.templates import CITIES

# city -> aliases as they appear in the wild (lowercased match)
_ALIASES: dict[str, list[str]] = {
    "Surat": ["surat", "सूरत", "સુરત"],
    "Ahmedabad": ["ahmedabad", "amdavad", "अहमदाबाद", "अमदावाद", "અમદાવાદ"],
    "Vadodara": ["vadodara", "baroda", "वडोदरा", "बड़ौदा", "વડોદરા"],
    "Rajkot": ["rajkot", "राजकोट", "રાજકોટ"],
    "Gandhinagar": ["gandhinagar", "गांधीनगर", "ગાંધીનગર"],
    "Bhavnagar": ["bhavnagar", "भावनगर", "ભાવનગર"],
    "Jamnagar": ["jamnagar", "जामनगर", "જામનગર"],
    "Junagadh": ["junagadh", "जूनागढ़", "જૂનાગઢ"],
}

# Place names that CONTAIN a city alias but are somewhere else entirely.
# Aliases are matched as substrings (so "#SuratRiots" still resolves), which
# means "Suratgarh" — a town in Rajasthan, ~1000km away — otherwise pins to
# Surat, Gujarat. These are stripped before matching, so a post naming both
# still resolves correctly.
_CONFUSABLES: list[str] = [
    "suratgarh", "सूरतगढ़", "सूरतगढ",       # Rajasthan
    "surate", "suratkhali",                  # Bangladesh (Suratkhali)
]


def city_search_terms() -> list[str]:
    """Every spelling of the target cities — English, Hindi, Gujarati and the
    romanized (Gujlish/Hinglish) forms — for collectors to query with."""
    from app.config import settings

    terms: list[str] = []
    for city in settings.TARGET_CITIES:
        for alias in _ALIASES.get(city, [city.lower()]):
            if alias not in terms:
                terms.append(alias)
    return terms


def _norm(s: str) -> str:
    """Lowercase + NFC. The normalisation is not optional for Indic text:
    ड़/ढ़ have both a precomposed form (U+095C/U+095D) and a base+nukta form
    (U+0921/U+0922 + U+093C). They render identically, so 'बड़ौदा' typed on one
    keyboard silently fails to match the same word typed on another. NFC folds
    both to one form."""
    return unicodedata.normalize("NFC", s).lower()


_NORM_ALIASES = {city: [_norm(a) for a in aliases] for city, aliases in _ALIASES.items()}
_NORM_CONFUSABLES = [_norm(c) for c in _CONFUSABLES]


def infer_city(text: str) -> tuple[str, float, float] | None:
    """Return (city, lat, lon) for the first known city mentioned, else None."""
    low = _norm(text)
    for bad in _NORM_CONFUSABLES:  # drop look-alike place names before matching
        low = low.replace(bad, " ")
    for city, aliases in _NORM_ALIASES.items():
        if any(a in low for a in aliases):
            lat, lon = CITIES.get(city, (0.0, 0.0))
            return city, lat, lon
    return None
