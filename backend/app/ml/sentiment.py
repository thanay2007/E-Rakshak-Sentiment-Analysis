# -*- coding: utf-8 -*-
"""Model #3 of the ensemble — context-aware multilingual valence lexicon.

The rule layer is ported from cjhutto/vaderSentiment and extended to
Hindi / Gujarati / Hinglish / Gujlish:
  • negation flips valence         ("not good", "accha nahi", "saru nathi")
  • boosters/dampeners scale it    ("bahut accha", "ekdam bakwas", "thoda")
  • ALL-CAPS words intensify       ("BAKWAS service")
  • ! / ? runs intensify           ("kya baat hai!!!")
VADER's published constants are kept (B_INCR 0.293, C_INCR 0.733,
N_SCALAR -0.74, ! amplifier 0.292) so the port is faithful.

What is NOT VADER — the context layer, which is why this model earns its place
next to two statistical ones:

  • **Contrast resolution.** VADER re-weights around "but" with fixed 0.5/1.5
    factors. Here the clause after the contrastive conjunction (ml/context.py
    `main_clause`) is treated as the author's actual position and the clause
    before it is discounted much harder, because "service kharab hati pan staff
    bahu saras" is a positive review with negative words in it.
  • **Irony inversion.** Praise terms sitting next to an irony cue ("wah kya
    service hai") have their sign flipped rather than counted as praise.
  • **Reported speech / conditional damping.** Valence inside relayed or
    hypothetical clauses is scaled down — the author is not asserting it.
  • **Every hit is returned as evidence** with the rule that modified it, so
    the drawer can show exactly which words produced the score. This model is
    the ensemble's explainability anchor: the two statistical models can only
    say "0.83 negative", this one says which word and which rule.

Unlike the other two it needs no training, which is exactly why it stays in the
ensemble — it cannot fail in the same way a fine-tune can.
"""
from __future__ import annotations

import re

from app.ml import lexicons as lx
from app.ml.context import TextContext, build_text_context, main_clause
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

_EXCLAIM_RE = re.compile(r"!")
_QM_RE = re.compile(r"\?")
_CAPS_RE = re.compile(r"\b[A-Z]{3,}\b")

LABELS = ("negative", "neutral", "positive")


def _token_spans(norm: str) -> list[tuple[str, int]]:
    """[(token, char_start)] over the normalized text."""
    return [(m.group(0), m.start()) for m in re.finditer(r"\S+", norm)]


def _hit_positions(norm: str, lexicon) -> list[tuple[str, float, int]]:
    """[(term, weight, char_pos)] for every lexicon term found, with location —
    positions let the rules inspect the words around each hit."""
    out = []
    for term, weight in match_terms(norm, lexicon):
        m = re.search(re.escape(term), norm, re.IGNORECASE)
        if m:
            out.append((term, weight, m.start()))
    return out


def _modified(weight: float, char_pos: int, spans, caps_positions: set[int]) -> tuple[float, list[str]]:
    """Apply negation / booster / caps rules to one lexicon hit.

    Returns (adjusted valence, names of the rules that fired) — the rule names
    become the evidence trail shown to the analyst.
    """
    rules: list[str] = []
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
            rules.append(f"negated by “{tok}”")
            break
        if tok in BOOSTERS:
            v += B_INCR * decay * (1 if v >= 0 else -1)
            rules.append(f"intensified by “{tok}”")
        elif tok in DAMPENERS:
            v -= B_INCR * decay * (1 if v >= 0 else -1)
            rules.append(f"softened by “{tok}”")
    # Hindi/Gujarati negation is postpositional ("accha NAHI hai", "saru NATHI")
    # — also look one token ahead
    if tok_idx + 1 < len(spans) and spans[tok_idx + 1][0].strip(".,!?").lower() in NEGATORS:
        v = -v * N_SCALAR
        rules.append(f"negated by trailing “{spans[tok_idx + 1][0].strip('.,!?')}”")
    if tok_idx in caps_positions:
        v += C_INCR * (1 if v >= 0 else -1) * 0.5
        rules.append("emphasised in capitals")
    return v, rules


def _collect(text: str, caps_positions_source: str, weight_scale: float,
             evidence: list[dict], clause: str) -> tuple[float, float]:
    """Score one clause. Returns (positive mass, negative mass)."""
    norm = normalize(clause)
    spans = _token_spans(norm)

    caps_words = _CAPS_RE.findall(caps_positions_source)
    all_caps_post = sum(1 for c in caps_positions_source if c.isupper()) > 0.6 * max(
        sum(1 for c in caps_positions_source if c.isalpha()), 1)
    caps_positions: set[int] = set()
    if caps_words and not all_caps_post:
        lowered = {w.lower() for w in caps_words}
        caps_positions = {i for i, (t, _) in enumerate(spans)
                          if t.strip(".,!?") in lowered}

    pos = neg = 0.0
    for lexicon, sign in ((lx.POSITIVE, 1.0), (lx.NEGATIVE, -1.0)):
        for term, weight, cp in _hit_positions(norm, lexicon):
            v, rules = _modified(sign * weight, cp, spans, caps_positions)
            v *= weight_scale
            pos += max(v, 0.0)
            neg += max(-v, 0.0)
            evidence.append({
                "term": term,
                "polarity": "positive" if v > 0 else "negative" if v < 0 else "neutral",
                "valence": round(v, 3),
                "rules": rules,
            })
    return pos, neg


def analyze_sentiment(text: str, threat_signals: dict | None = None,
                      tctx: TextContext | None = None) -> dict:
    """Context-aware lexicon sentiment.

    Returns {label, score, confidence, probs, evidence} where score ∈ [-1,+1]
    and evidence lists the lexicon terms with the rules that modified each.
    """
    tctx = tctx or build_text_context(text)
    evidence: list[dict] = []

    # ── contrast: weigh the asserted clause, discount what precedes it ───────
    if tctx.has_contrast:
        asserted = main_clause(text)
        preceding = text[: len(text) - len(asserted)] if asserted != text else ""
        pos, neg = _collect(text, text, 1.0, evidence, asserted)
        if preceding.strip():
            p2, n2 = _collect(text, text, 0.35, evidence, preceding)
            pos, neg = pos + p2, neg + n2
    else:
        pos, neg = _collect(text, text, 1.0, evidence, text)

    # ── irony: praise next to an irony cue means the opposite ───────────────
    if tctx.has_sarcasm_cue and pos > neg:
        pos, neg = neg, pos * 0.85
        evidence.append({"term": "(irony cue)", "polarity": "negative",
                         "valence": -round(neg, 3),
                         "rules": ["praise inverted — irony marker present"]})

    # punctuation emphasis pushes whichever pole is already winning
    emphasis = min(len(_EXCLAIM_RE.findall(text)), 4) * EP_AMP \
        + min(len(_QM_RE.findall(text)), 3) * QM_AMP
    if emphasis and pos != neg:
        if pos > neg:
            pos += emphasis * 0.5
        else:
            neg += emphasis * 0.5

    # Abusive/hostile language is intrinsically negative even without valence words
    if threat_signals:
        neg += 0.9 * threat_signals.get("violence", 0)
        neg += 0.7 * threat_signals.get("hostility", 0)
        neg += 0.5 * threat_signals.get("abuse", 0)

    pos += 0.3 * sum(1 for ch in text if ch in lx.POSITIVE_EMOJI)
    neg += 0.3 * sum(1 for ch in text if ch in lx.NEGATIVE_EMOJI)

    # ── context damping: relayed or hypothetical valence is not asserted ─────
    damp = 1.0
    if tctx.is_reported:
        damp *= 0.75
    if tctx.is_conditional:
        damp *= 0.85
    if tctx.is_question and not tctx.is_first_person:
        damp *= 0.90
    pos *= damp
    neg *= damp

    value = (pos - neg) / (pos + neg + 0.8)  # smoothed, bounded (-1, 1)
    value = max(-1.0, min(1.0, value))
    if value > 0.12:
        label = "positive"
    elif value < -0.12:
        label = "negative"
    else:
        label = "neutral"

    # confidence rises with valence magnitude and with how much evidence there
    # is; a single weak hit should not look as certain as five agreeing ones.
    mass = min(1.0, (pos + neg) / 3.0)
    confidence = round(min(0.95, 0.40 + abs(value) * 0.45 + mass * 0.15), 4)

    # probability triple, so this model plugs into the ensemble like the others
    mag = abs(value)
    if label == "neutral":
        probs = {"neutral": round(0.5 + (0.12 - mag) * 2, 4)}
        rest = round((1 - probs["neutral"]) / 2, 4)
        probs["positive"] = probs["negative"] = rest
    else:
        probs = {label: round(0.34 + mag * 0.6, 4)}
        other = "negative" if label == "positive" else "positive"
        probs["neutral"] = round((1 - probs[label]) * 0.7, 4)
        probs[other] = round(1 - probs[label] - probs["neutral"], 4)

    evidence.sort(key=lambda e: -abs(e["valence"]))
    return {
        "label": label,
        "score": round(value, 3),
        "confidence": confidence,
        "probs": {k: probs[k] for k in LABELS},
        "evidence": evidence[:8],
    }
