# -*- coding: utf-8 -*-
"""Lite multilingual sentiment: valence lexicons + VADER-style heuristics.

The rule layer is ported from cjhutto/vaderSentiment and extended to
Hindi / Gujarati / Hinglish / Gujlish:
  • negation flips valence         ("not good", "accha nahi", "saru nathi")
  • boosters/dampeners scale it    ("bahut accha", "ekdam bakwas", "thoda")
  • ALL-CAPS words intensify       ("BAKWAS service")
  • ! / ? runs intensify           ("kya baat hai!!!")
  • contrastive conjunction re-weights the clause after but/lekin/pan
VADER's published constants are kept (B_INCR 0.293, C_INCR 0.733,
N_SCALAR -0.74, ! amplifier 0.292) so the port is faithful.

Replaced by the fine-tuned MuRIL sentiment model in full mode.
"""
import re

from app.ml import lexicons as lx
from app.ml.matcher import match_terms
from app.ml.normalize import normalize

# VADER constants (Hutto & Gilbert 2014)
B_INCR, C_INCR, N_SCALAR, EP_AMP, QM_AMP = 0.293, 0.733, 0.74, 0.292, 0.18

NEGATORS = {
    "not", "no", "never", "neither", "nor", "cannot", "cant", "dont", "wont",
    "isnt", "wasnt", "didnt", "doesnt", "aint", "without",
    "nahi", "na", "mat", "bina", "kabhi",                  # Hindi / Hinglish
    "nathi", "nahin", "nai",                               # Gujarati / Gujlish
    "नहीं", "ना", "मत", "कभी", "बिना",
    "નથી", "ના", "નહીં", "કદી",
}
BOOSTERS = {
    "very", "really", "so", "too", "extremely", "totally", "completely",
    "absolutely", "super", "full", "always",
    "bahut", "bohot", "bilkul", "ekdam", "puri", "pura", "sach", "zyada",
    "khub", "bau", "ghanu", "ekdum",                       # Gujarati / Gujlish
    "बहुत", "बिल्कुल", "एकदम", "ज्यादा", "पूरी",
    "ખૂબ", "બહુ", "એકદમ", "ઘણું", "ઘણી",
}
DAMPENERS = {
    "slightly", "somewhat", "kinda", "barely", "hardly", "little", "bit",
    "thoda", "thodi", "zara", "kam", "halka",
    "थोड़ा", "थोड़ी", "जरा", "कम",
    "થોડું", "થોડી", "જરા", "ઓછું",
}
CONTRASTIVES = {"but", "however", "lekin", "magar", "par", "kintu", "parantu",
                "पर", "लेकिन", "मगर", "किंतु", "પણ", "પરંતુ"}

_EXCLAIM_RE = re.compile(r"!")
_QM_RE = re.compile(r"\?")
_CAPS_RE = re.compile(r"\b[A-Z]{3,}\b")


def _token_spans(norm: str) -> list[tuple[str, int]]:
    """[(token, char_start)] over the normalized text."""
    return [(m.group(0), m.start()) for m in re.finditer(r"\S+", norm)]


def _hit_positions(norm: str, lexicon) -> list[tuple[float, int]]:
    """[(weight, char_pos)] for every lexicon term found, with its location —
    positions let the VADER rules inspect the words around each hit."""
    out = []
    for term, weight in match_terms(norm, lexicon):
        for m in re.finditer(re.escape(term), norm, re.IGNORECASE):
            out.append((weight, m.start()))
            break  # first occurrence is enough per term
    return out


def _modified(weight: float, char_pos: int, spans, contrast_pos: int | None,
              caps_positions: set[int]) -> float:
    """Apply negation / booster / caps / contrast rules to one lexicon hit."""
    tok_idx = 0
    for i, (_, start) in enumerate(spans):
        if start <= char_pos:
            tok_idx = i
    v = weight
    # look back up to 3 tokens (VADER window), decayed 5%/10% with distance
    for back in range(1, 4):
        j = tok_idx - back
        if j < 0:
            break
        tok = spans[j][0].strip(".,!?").lower()
        decay = (1.0, 0.95, 0.90)[back - 1]
        if tok in NEGATORS:
            v = -v * N_SCALAR   # flip polarity, scaled (VADER N_SCALAR)
            break
        if tok in BOOSTERS:
            v += B_INCR * decay * (1 if v >= 0 else -1)
        elif tok in DAMPENERS:
            v -= B_INCR * decay * (1 if v >= 0 else -1)
    # Hindi/Gujarati negation is postpositional ("accha NAHI hai",
    # "saru NATHI") — also look one token ahead
    if tok_idx + 1 < len(spans) and spans[tok_idx + 1][0].strip(".,!?").lower() in NEGATORS:
        v = -v * N_SCALAR
    if tok_idx in caps_positions:
        v += C_INCR * (1 if v >= 0 else -1) * 0.5
    if contrast_pos is not None:
        v *= 0.5 if char_pos < contrast_pos else 1.5   # VADER: clause after "but" wins
    return v


def analyze_sentiment(text: str, threat_signals: dict | None = None) -> tuple[str, float]:
    """Returns (label, score) with score in [-1, +1]."""
    norm = normalize(text)
    spans = _token_spans(norm)

    contrast_pos = None
    for tok, start in spans:
        if tok.strip(".,!?").lower() in CONTRASTIVES:
            contrast_pos = start
            break
    # caps emphasis only counts when the whole post isn't shouting
    caps_words = _CAPS_RE.findall(text)
    all_caps_post = sum(1 for c in text if c.isupper()) > 0.6 * max(
        sum(1 for c in text if c.isalpha()), 1)
    caps_positions: set[int] = set()
    if caps_words and not all_caps_post:
        lowered = {w.lower() for w in caps_words}
        caps_positions = {i for i, (t, _) in enumerate(spans)
                          if t.strip(".,!?") in lowered}

    pos = neg = 0.0
    for weight, cp in _hit_positions(norm, lx.POSITIVE):
        v = _modified(weight, cp, spans, contrast_pos, caps_positions)
        pos += max(v, 0.0)
        neg += max(-v, 0.0)
    for weight, cp in _hit_positions(norm, lx.NEGATIVE):
        v = _modified(-weight, cp, spans, contrast_pos, caps_positions)
        neg += max(-v, 0.0)
        pos += max(v, 0.0)

    # punctuation emphasis pushes whichever pole is already winning
    emphasis = min(_EXCLAIM_RE.findall(text).__len__(), 4) * EP_AMP \
        + min(_QM_RE.findall(text).__len__(), 3) * QM_AMP
    if emphasis and pos != neg:
        if pos > neg:
            pos += emphasis * 0.5
        else:
            neg += emphasis * 0.5

    # Threat language is intrinsically negative even without valence words
    if threat_signals:
        neg += 0.9 * threat_signals.get("violence", 0)
        neg += 0.7 * threat_signals.get("hostility", 0)
        neg += 0.5 * threat_signals.get("abuse", 0)
        neg += 0.3 * threat_signals.get("fake_markers", 0)

    pos += 0.3 * sum(1 for ch in text if ch in lx.POSITIVE_EMOJI)
    neg += 0.3 * sum(1 for ch in text if ch in lx.NEGATIVE_EMOJI)

    value = (pos - neg) / (pos + neg + 0.8)  # smoothed, bounded (-1, 1)
    value = max(-1.0, min(1.0, value))
    if value > 0.12:
        label = "positive"
    elif value < -0.12:
        label = "negative"
    else:
        label = "neutral"
    return label, round(value, 3)
