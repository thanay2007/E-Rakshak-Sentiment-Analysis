# -*- coding: utf-8 -*-
"""City geo-tagging for live-platform posts.

Simulated posts carry their city; posts from real APIs usually don't. When a
collector didn't already geo-tag a post (seed page/subreddit :City suffix),
infer the city from mentions in the text — covering English, Hindi and
Gujarati spellings of the deployment's target cities.
"""
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


def infer_city(text: str) -> tuple[str, float, float] | None:
    """Return (city, lat, lon) for the first known city mentioned, else None."""
    low = text.lower()
    for city, aliases in _ALIASES.items():
        if any(a in low for a in aliases):
            lat, lon = CITIES.get(city, (0.0, 0.0))
            return city, lat, lon
    return None
