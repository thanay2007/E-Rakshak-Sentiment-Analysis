"""Helpers shared by more than one collector adapter.

Nothing platform-specific lives here — these are the two pieces every adapter
that reads free text from a rotating roster of seed sources needs, and both are
easy to get subtly wrong in a way that only shows up in production.
"""
import re

# Hashtag body = word characters, and \w alone is not enough. It is Unicode-
# aware, but only for letters and digits (categories L*/N*) — combining marks
# are excluded, and every Indic vowel sign, anusvara and virama is one. Plain
# r"#(\w+)" therefore truncates #आंदोलन to "आ" at the anusvara, which on a
# Gujarat deployment silently guts most local-script tags while looking fine in
# English. These ranges add the marks back for Devanagari and Gujarati, plus
# ZWJ/ZWNJ, which sit *inside* correctly spelled Indic words.
_MARKS = (r"̀-ͯ"              # generic combining diacriticals
          r"ऀ-ःऺ-ॏ॑-ॗॢ-ॣ"  # Devanagari
          r"ઁ-ઃ઼-્ૢ-ૣ"              # Gujarati
          r"‌‍")              # ZWNJ / ZWJ
# Stops at the punctuation in "#surat,#protest" and "#rajkot." — a whitespace
# split returns the first as one unusable token and keeps the trailing dot on
# the second.
_HASHTAG_RE = re.compile(rf"#([\w{_MARKS}]+)", re.UNICODE)


def extract_hashtags(text: str) -> list[str]:
    """Deduped, case-folded, order preserved — platforms treat #Surat and
    #surat as one tag and so must the trend counter."""
    out, seen = [], set()
    for tag in _HASHTAG_RE.findall(text or ""):
        low = tag.lower()
        if low not in seen:
            seen.add(low)
            out.append(low)
    return out


def rotate(items: list, cursor: int, size: int) -> tuple[list, int]:
    """A `size`-long slice starting where the last cycle stopped, wrapping
    round. Taking items[:size] every cycle — which is the obvious version —
    means the roster's (size+1)th entry onwards is never read at all."""
    if not items or size <= 0:
        return [], cursor
    n = len(items)
    start = cursor % n
    take = min(size, n)
    return [items[(start + i) % n] for i in range(take)], start + take
