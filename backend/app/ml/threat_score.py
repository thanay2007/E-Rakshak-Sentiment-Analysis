"""Composite 0-100 threat score.

Formula (documented for judges; weights sum to 1.0):

    threat_score = 100 * clamp01(
        0.40 * severity(label) * confidence   # what the classifier believes, scaled by class danger
      + 0.25 * toxicity                       # hate/abuse intensity incl. code-mixed slurs
      + 0.20 * virality                       # log-scaled engagement + coordinated amplification
      + 0.15 * keyword_severity )             # strongest lexicon term matched (e.g. "जला दो" = 1.0)

    severity: Incitement to Violence 1.00 | Inflammatory 0.75 | Fake News 0.65 | Neutral 0.05
    virality: min(1, log10(1 + likes + 3*shares + 2*comments + views/50) / 4), +0.15 if the
              post is part of a detected amplification burst (capped at 1).

Interpretation bands used across the product (defaults, env-tunable):
    >= CRITICAL_THRESHOLD (74)  critical alert + auto-generated escalation template
    >= ALERT_THRESHOLD    (65)  high alert
    >= 50                       "active threat" (dashboard KPI)
The classifier's softmax spreads probability across 4 classes, so even a
confident incitement post tops out near ~80 — bands are calibrated to that.
"""
import math

SEVERITY = {
    "Incitement to Violence": 1.00,
    "Inflammatory": 0.75,
    "Fake News": 0.65,
    "Neutral": 0.05,
}


def virality(engagement: dict, is_amplified: bool) -> float:
    likes = engagement.get("likes", 0)
    shares = engagement.get("shares", 0)
    comments = engagement.get("comments", 0)
    views = engagement.get("views", 0)
    v = min(1.0, math.log10(1 + likes + 3 * shares + 2 * comments + views / 50) / 4)
    if is_amplified:
        v = min(1.0, v + 0.15)
    return v


def threat_score(label: str, confidence: float, toxicity: float,
                 engagement: dict, is_amplified: bool, keyword_severity: float) -> float:
    v = virality(engagement or {}, is_amplified)
    raw = (
        0.40 * SEVERITY.get(label, 0.05) * confidence
        + 0.25 * toxicity
        + 0.20 * v
        + 0.15 * keyword_severity
    )
    return round(max(0.0, min(1.0, raw)) * 100, 1)
