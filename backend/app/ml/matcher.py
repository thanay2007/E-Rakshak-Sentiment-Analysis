"""Shared lexicon matcher.

Both scripts follow the same rule: a term must start where a word starts, and
may carry an inflectional tail. What differs is only how "where a word starts"
is spelled, because Python's `\\b` is defined over `\\w`, which already contains
Indic letters *and* their combining marks — so there is no `\\b` between `નીચ`
and the `ે` that follows it, and none between `સારી` and the `નવ` before it.

Indic matching used to be a bare `term in text`. Measured on the live corpus
that was matching terms in the middle of unrelated words, and the term severity
it produced was feeding the concern score of ordinary civic posts:

    સારી   inside  નવસારી      Navsari, a city
    ડર     inside  મર્ડર, ટેંડર, ડિવાઇડર
    મારો   inside  તમારો "your", સમારોહ "ceremony"
    આનંદ   inside  આનંદનગર (a place), આનંદીબેન (a person)

A leading boundary removes all of those. It must NOT also remove the trailing
tail, because that tail is where Indic inflection lives and it is nearly always
the same word:

    सबक सिखा  ->  सबक सिखाना   287 posts — the infinitive, same phrase
    નેતા      ->  નેતાઓ        the plural
    धन्यवाद   ->  धन्यवाद।     merely punctuation

Two lists carry the exceptions that a boundary rule cannot express on its own:

`EXACT_ONLY` — stems whose *tail* form is a different word. This is the `નીચ`
case from the audit: `નીચ` is a slur, `નીચે` is "below" and `નીચાણવાળા` is
"low-lying", and 40 of the 49 corpus matches were flood and bridge reports.
These get no tail at all.

`INFIX_OK` — terms that legitimately live inside a compound, which is how Indic
builds titles. Dropping these would lose `મુખ્યમંત્રી` (chief minister) and
`પ્રધાનમંત્રી` (prime minister) from a lexicon whose entire job is spotting
mentions of officials, so they keep plain substring matching.

Both lists are deliberately small, explicit and reviewable. A term list that
feeds a number an officer acts on should fail in ways someone can read.
"""
import re
from functools import lru_cache

#: Anything that continues an Indic orthographic word: letters, vowel signs,
#: virama, nukta, and the joiners that hold conjuncts together.
_INDIC_CONT = "ऀ-ॿ઀-૿꣠-ꣿ‌‍"

#: Stems whose inflected form is a *different* word — no tail allowed.
EXACT_ONLY = frozenset({
    "નીચ",    # slur; નીચે "below", નીચાણવાળા "low-lying"
    "नीच",    # same stem in Devanagari
    "દર્દ",   # "pain"; દર્દી "patient" is a hospital report, not distress
    "ખુશ",    # "happy"; ખુશખબર/ખુશહાલ are their own words
    # Word-initial, so the leading boundary cannot help: આનંદનગર is a
    # neighbourhood of Ahmedabad and આનંદીબેન is a former chief minister.
    # Costs the genitive આનંદની (3 posts) to drop 13 place and person names.
    "આનંદ", "आनंद",
})

#: Terms that legitimately appear inside a compound — plain substring matching.
INFIX_OK = frozenset({
    "મંત્રી", "मंत्री",   # મુખ્યમંત્રી, પ્રધાનમંત્રી, ગૃહમંત્રી
    "ભ્રષ્ટ", "भ्रष्ट",   # ભ્રષ્ટાચાર "corruption"
})


def _is_latin(term: str) -> bool:
    return all(ord(c) < 0x0900 for c in term)


@lru_cache(maxsize=4096)
def _latin_re(term: str) -> re.Pattern:
    # Leading word boundary, but allow inflected suffixes ("sikha" -> "sikhana",
    # "attack" -> "attacked") — essential for romanized Hindi/Gujarati stems.
    return re.compile(r"\b" + re.escape(term) + r"\w*", re.IGNORECASE)


@lru_cache(maxsize=4096)
def _indic_re(term: str) -> re.Pattern:
    """Leading Indic word boundary; trailing tail unless the stem is EXACT_ONLY."""
    tail = f"(?![{_INDIC_CONT}])" if term in EXACT_ONLY else ""
    return re.compile(f"(?<![{_INDIC_CONT}]){re.escape(term)}{tail}")


@lru_cache(maxsize=4096)
def _pattern(term: str) -> re.Pattern:
    if _is_latin(term):
        return _latin_re(term)
    if term in INFIX_OK:
        return re.compile(re.escape(term))
    return _indic_re(term)


def match_terms(norm_text: str, lexicon: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Return [(term, weight)] for every lexicon entry found in the normalized text."""
    hits = []
    for term, weight in lexicon:
        if _pattern(term).search(norm_text):
            hits.append((term, weight))
    return hits


def score(hits: list[tuple[str, float]]) -> float:
    """Aggregate hit weights with diminishing returns (w1 + 0.6*w2 + 0.36*w3 ...)
    so one strong term dominates but stacked weak terms still add up."""
    total = 0.0
    for i, (_, w) in enumerate(sorted(hits, key=lambda h: -h[1])):
        total += w * (0.6 ** i)
    return total
