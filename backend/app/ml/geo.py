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
    """Return (city, lat, lon) for the first known city mentioned, else None.

    "First" means first in the alias table, not first in the text — fine for a
    short post, which usually names one place. Use `dominant_city` for anything
    long enough to name several.
    """
    low = _norm(text)
    for bad in _NORM_CONFUSABLES:  # drop look-alike place names before matching
        low = low.replace(bad, " ")
    for city, aliases in _NORM_ALIASES.items():
        if any(a in low for a in aliases):
            lat, lon = CITIES.get(city, (0.0, 0.0))
            return city, lat, lon
    return None


def dominant_city(text: str) -> tuple[str, float, float] | None:
    """The city a longer text is actually *about*, not merely the first it names.

    A YouTube description names several places — the incident's city, the
    channel's own city, the other cities in its coverage list. `infer_city`
    answers with whichever comes first in the alias table, so a bulletin
    titled "Rajkot Bad Roads" was filed under Ahmedabad because the
    description mentioned it further down. Most mentions wins; a tie goes to
    whichever is named earliest in the text, which is nearly always the
    headline.
    """
    low = _norm(text)
    for bad in _NORM_CONFUSABLES:
        low = low.replace(bad, " ")
    scored: list[tuple[int, int, str]] = []
    for city, aliases in _NORM_ALIASES.items():
        hits = sum(low.count(a) for a in aliases)
        if not hits:
            continue
        first = min((low.find(a) for a in aliases if a in low), default=len(low))
        scored.append((-hits, first, city))
    if not scored:
        return None
    scored.sort()
    city = scored[0][2]
    lat, lon = CITIES.get(city, (0.0, 0.0))
    return city, lat, lon
