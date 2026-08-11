# -*- coding: utf-8 -*-
"""Composite 0-100 concern score, derived from sentiment.

This replaces the old threat-category score. The model no longer claims a post
"is incitement" or "is fake news" — those are investigative conclusions a
sentiment model has no basis for. What it does claim is how negative a post is,
how confidently, how abusive its language is, and how far it travelled. That is
what this number aggregates, and it is the only number the alert bands read.

    concern = 100 × clamp01(
          0.50 × negativity × confidence   # how negative, scaled by how sure
        + 0.22 × toxicity                  # abusive/hateful language intensity
        + 0.18 × virality                  # log-scaled reach + amplification
        + 0.10 × term_severity )           # strongest matched lexicon term

    negativity = max(0, −sentiment_score)   ∈ [0,1]  (positive posts contribute 0)

Bands (env-tunable via ALERT_THRESHOLD / CRITICAL_THRESHOLD):
    ≥ 74  critical — strongly negative AND abusive AND spreading
    ≥ 65  high
    ≥ 50  elevated ("needs a look" on the dashboard)
    < 50  routine

The weights are deliberately shaped so no single dimension can reach an alert
band alone: a furious post nobody read tops out near 50, and a viral cheerful
post cannot climb past ~30. An alert therefore always means "negative *and*
travelling", which is the only combination worth an analyst's time.
"""
from __future__ import annotations

import math

W_SENTIMENT = 0.50
W_TOXICITY = 0.22
W_VIRALITY = 0.18
W_TERMS = 0.10

FORMULA = (
    "concern = 100 × ( 0.50 × negativity × confidence"
    " + 0.22 × toxicity + 0.18 × virality + 0.10 × term_severity )"
)


def virality(engagement: dict, is_amplified: bool) -> float:
    """Log-scaled interaction volume in [0,1]; amplified bursts get +0.15."""
    e = engagement or {}
    raw = (e.get("likes", 0) + 3 * e.get("shares", 0)
           + 2 * e.get("comments", 0) + e.get("views", 0) / 50)
    v = min(1.0, math.log10(1 + max(0, raw)) / 4)
    if is_amplified:
        v = min(1.0, v + 0.15)
    return v


def concern_score(
    sentiment_score: float,
    confidence: float,
    toxicity: float,
    engagement: dict,
    is_amplified: bool,
    term_severity: float,
) -> tuple[float, list[dict]]:
    """Returns (score 0-100, contribution breakdown).

    The breakdown is not decoration — it is what the drawer renders under
    "how this score was built", so an analyst can see that a 71 came from
    virality rather than from the language itself.
    """
    negativity = max(0.0, -float(sentiment_score))
    v = virality(engagement, is_amplified)
    conf = max(0.0, min(1.0, float(confidence)))
    tox = max(0.0, min(1.0, float(toxicity or 0.0)))
    terms = max(0.0, min(1.0, float(term_severity or 0.0)))

    parts = [
        {"factor": "Negative sentiment", "weight": W_SENTIMENT,
         "input": round(negativity * conf, 3),
         "points": round(100 * W_SENTIMENT * negativity * conf, 1),
         "detail": f"negativity {negativity:.2f} × model confidence {conf:.2f}"},
        {"factor": "Toxic language", "weight": W_TOXICITY,
         "input": round(tox, 3),
         "points": round(100 * W_TOXICITY * tox, 1),
         "detail": "abuse/slur intensity from the toxicity model"},
        {"factor": "Reach & amplification", "weight": W_VIRALITY,
         "input": round(v, 3),
         "points": round(100 * W_VIRALITY * v, 1),
         "detail": ("engagement volume, log-scaled"
                    + (" · inside an amplification burst" if is_amplified else ""))},
        {"factor": "Matched terms", "weight": W_TERMS,
         "input": round(terms, 3),
         "points": round(100 * W_TERMS * terms, 1),
         "detail": "strongest lexicon term matched in the post"},
    ]
    raw = sum(p["points"] for p in parts)
    return round(max(0.0, min(100.0, raw)), 1), parts


def band(score: float) -> str:
    """Score → the word the UI shows next to it."""
    from app.config import settings

    if score >= settings.CRITICAL_THRESHOLD:
        return "critical"
    if score >= settings.ALERT_THRESHOLD:
        return "high"
    if score >= 50:
        return "elevated"
    return "routine"
