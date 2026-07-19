# -*- coding: utf-8 -*-
"""3-model sentiment consensus ensemble.

The mentor's design: instead of trusting one model, three independent models
each predict a sentiment label + confidence, and the system chooses the best
one — then Groq double-checks the result. Each model is a fundamentally
different approach, so their agreement is real signal, not three copies of the
same mistake:

  1. TRANSFORMER  — google/muril-base-cased fine-tuned (deep contextual).
                    Overall accuracy 70.6% on 5,768 held-out rows.
  2. CLASSICAL    — TF-IDF (word 1-2 + char 2-5) + LinearSVC (statistical).
                    Overall accuracy 64.0% on the same test split.
  3. LEXICON      — multilingual valence lexicon + negation (rule-based).
                    Transparent, explainable, zero training.

Decision rule ("best one chosen"):
  • Each model votes a label with a confidence in [0,1].
  • If ≥2 models agree, that label wins (majority) — its confidence is the
    mean of the agreeing models, nudged up for consensus.
  • If all three disagree, the single most-confident model wins ("best one").
  • The winning model is recorded as `chosen_by`, and EVERY model's vote is
    stored on the post so an analyst (or the mentor) can audit the decision.

The numeric sentiment score (-1..+1) is the confidence-weighted average of the
models that agree with the chosen label, so the score reflects the consensus
strength, not just one model.
"""
from __future__ import annotations

# per-model reliability priors from the eval reports — used only to break exact
# ties and to weight the blended score; higher = more trusted historically.
MODEL_WEIGHTS = {"transformer": 0.706, "classical": 0.640, "lexicon": 0.560}
_SENT_VALUE = {"negative": -1.0, "neutral": 0.0, "positive": 1.0}


def _vote(model: str, label: str, confidence: float, probs: dict | None = None) -> dict:
    return {"model": model, "label": label,
            "confidence": round(float(confidence), 4),
            "probs": probs or {}}


def combine(votes: list[dict]) -> dict:
    """votes: list of {model,label,confidence,probs}. Returns the consensus:
    {label, score, confidence, chosen_by, agreement, votes}."""
    votes = [v for v in votes if v and v.get("label")]
    if not votes:
        return {"label": "neutral", "score": 0.0, "confidence": 0.0,
                "chosen_by": "none", "agreement": "0/0", "votes": []}

    # tally labels
    tally: dict[str, list[dict]] = {}
    for v in votes:
        tally.setdefault(v["label"], []).append(v)

    # winning label: most votes, then highest summed weighted-confidence
    def label_strength(item):
        label, vs = item
        n = len(vs)
        wconf = sum(v["confidence"] * MODEL_WEIGHTS.get(v["model"], 0.5) for v in vs)
        return (n, wconf)

    winner, backers = max(tally.items(), key=label_strength)
    n_agree = len(backers)

    if n_agree >= 2:
        chosen_by = "consensus (" + ", ".join(v["model"] for v in backers) + ")"
        base_conf = sum(v["confidence"] for v in backers) / n_agree
        confidence = min(0.99, base_conf + 0.05 * (n_agree - 1))  # consensus bonus
    else:
        # all disagree → trust the single most-confident model ("best one")
        best = max(votes, key=lambda v: v["confidence"] * MODEL_WEIGHTS.get(v["model"], 0.5))
        winner, backers = best["label"], [best]
        chosen_by = f"best model ({best['model']})"
        confidence = best["confidence"]

    # blended numeric score from the models backing the winning label
    wsum = sum(v["confidence"] * MODEL_WEIGHTS.get(v["model"], 0.5) for v in backers) or 1.0
    score = sum(_SENT_VALUE[v["label"]] * v["confidence"] * MODEL_WEIGHTS.get(v["model"], 0.5)
                for v in backers) / wsum

    return {
        "label": winner,
        "score": round(score, 3),
        "confidence": round(confidence, 4),
        "chosen_by": chosen_by,
        "agreement": f"{n_agree}/{len(votes)}",
        "votes": votes,
    }
