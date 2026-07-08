"""Shared lexicon matcher. Latin terms use word boundaries; Indic terms use
substring matching (word boundaries are unreliable across matras/conjuncts)."""
import re
from functools import lru_cache


def _is_latin(term: str) -> bool:
    return all(ord(c) < 0x0900 for c in term)


@lru_cache(maxsize=4096)
def _latin_re(term: str) -> re.Pattern:
    # Leading word boundary, but allow inflected suffixes ("sikha" -> "sikhana",
    # "attack" -> "attacked") — essential for romanized Hindi/Gujarati stems.
    return re.compile(r"\b" + re.escape(term) + r"\w*", re.IGNORECASE)


def match_terms(norm_text: str, lexicon: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Return [(term, weight)] for every lexicon entry found in the normalized text."""
    hits = []
    for term, weight in lexicon:
        if _is_latin(term):
            if _latin_re(term).search(norm_text):
                hits.append((term, weight))
        elif term in norm_text:
            hits.append((term, weight))
    return hits


def score(hits: list[tuple[str, float]]) -> float:
    """Aggregate hit weights with diminishing returns (w1 + 0.6*w2 + 0.36*w3 ...)
    so one strong term dominates but stacked weak terms still add up."""
    total = 0.0
    for i, (_, w) in enumerate(sorted(hits, key=lambda h: -h[1])):
        total += w * (0.6 ** i)
    return total
