# -*- coding: utf-8 -*-
"""3-model sentiment consensus, with Groq as the final check.

Instead of trusting one model, three independent models each predict
positive / negative / neutral with a confidence, the best answer is chosen from
those three, and then Groq reviews the chosen answer and can overturn it. Each
model is a fundamentally different approach, so their agreement is real signal
rather than three copies of the same mistake:

  1. TRANSFORMER  — google/muril-base-cased fine-tuned (deep contextual).
  2. CLASSICAL    — TF-IDF (word 1-2 + char 2-5) + LinearSVC (statistical).
  3. LEXICON      — multilingual valence lexicon + VADER rules (explainable).

All three consume the same context-tagged input (ml/context.py), so "context"
is not a post-hoc adjustment bolted onto bag-of-words predictions — it is part
of what every model sees.

**Decision rule.**
  • If ≥2 models agree, that label wins; its confidence is the mean of the
    agreeing models plus a consensus bonus.
  • If all three disagree, the single most-confident model wins, weighted by
    each model's historical reliability — "the best model's answer is chosen".
  • Metadata context (account, reach, amplification) then adjusts the
    CONFIDENCE only, never the label, and every adjustment carries a reason.
  • Finally Groq sees the post and the ensemble's verdict. Agreement raises
    confidence; a confident disagreement (≥ GROQ_OVERRIDE_CONFIDENCE) replaces
    the label and is recorded as an override — never silently.

Every model's vote, every context adjustment and Groq's verdict are stored on
the post so an analyst can audit exactly how a label was reached.
"""
from __future__ import annotations

from app.ml.context import MetaContext, TextContext, context_adjustments

# per-model reliability priors from the eval reports — used to break ties and
# to weight the blended score; higher = more trusted historically.
MODEL_WEIGHTS = {"transformer": 0.706, "classical": 0.640, "lexicon": 0.560}
SENT_VALUE = {"negative": -1.0, "neutral": 0.0, "positive": 1.0}
LABELS = ("negative", "neutral", "positive")

MODEL_DESCRIPTIONS = {
    "transformer": "MuRIL fine-tune — deep contextual model over the post text",
    "classical": "TF-IDF word+char n-grams with LinearSVC — statistical model",
    "lexicon": "Multilingual valence lexicon with negation/irony rules",
    "groq": "LLM final check — independent reading of the post",
}

# How sure Groq must be before it is allowed to overturn three models that
# looked at the same text. Below this it is recorded as a dissent, not a verdict.
GROQ_OVERRIDE_CONFIDENCE = 0.75


def vote(model: str, label: str, confidence: float, probs: dict | None = None,
         evidence: list | None = None) -> dict:
    return {"model": model, "label": label,
            "confidence": round(float(confidence), 4),
            "probs": probs or {},
            "evidence": evidence or []}


def _blended_score(backers: list[dict]) -> float:
    """Numeric sentiment in [-1,1] from the models backing the winning label.

    Uses each model's full probability triple where available, so a model that
    said 55% negative moves the score less than one that said 95% negative.
    """
    total_w = 0.0
    acc = 0.0
    for v in backers:
        w = MODEL_WEIGHTS.get(v["model"], 0.5)
        probs = v.get("probs") or {}
        if probs and all(l in probs for l in LABELS):
            val = probs["positive"] - probs["negative"]
        else:
            val = SENT_VALUE.get(v["label"], 0.0) * v["confidence"]
        acc += val * w
        total_w += w
    return acc / total_w if total_w else 0.0


def combine(votes: list[dict], tctx: TextContext | None = None,
            mctx: MetaContext | None = None) -> dict:
    """votes: [{model,label,confidence,probs,evidence}] → the consensus record."""
    votes = [v for v in votes if v and v.get("label") in LABELS]
    if not votes:
        return {"label": "neutral", "score": 0.0, "confidence": 0.0,
                "chosen_by": "none", "agreement": "0/0", "votes": [],
                "context_adjustments": [], "evidence": []}

    tally: dict[str, list[dict]] = {}
    for v in votes:
        tally.setdefault(v["label"], []).append(v)

    def label_strength(item):
        label, vs = item
        wconf = sum(v["confidence"] * MODEL_WEIGHTS.get(v["model"], 0.5) for v in vs)
        return (len(vs), wconf)

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

    score = _blended_score(backers)

    # ── context calibration: confidence only, label untouched ───────────────
    adjustments: list[dict] = []
    if tctx is not None and mctx is not None:
        adjustments = context_adjustments(tctx, mctx)
        confidence = max(0.05, min(0.99, confidence + sum(a["delta"] for a in adjustments)))
        # a damped reading should also produce a less extreme number
        damp = 1.0 + min(0.0, sum(a["delta"] for a in adjustments))
        score *= max(0.55, damp)

    return {
        "label": winner,
        "score": round(max(-1.0, min(1.0, score)), 3),
        "confidence": round(confidence, 4),
        "chosen_by": chosen_by,
        "agreement": f"{n_agree}/{len(votes)}",
        "votes": votes,
        "context_adjustments": adjustments,
        "evidence": [],   # filled by build_evidence() once all sources are known
    }


# ── Groq: the final check ───────────────────────────────────────────────────

def apply_groq_check(consensus: dict, groq_label: str, groq_confidence: float,
                     groq_reason: str = "", groq_quotes: list | None = None,
                     model_used: str = "") -> dict:
    """Fold Groq's independent reading into the consensus (mutates and returns).

    Groq is the last word, not an equal fourth vote: it sees the post AFTER the
    three models have spoken, so treating it as a peer would double-count the
    same evidence. It either confirms (confidence up), dissents without enough
    certainty to act (recorded, nothing changes), or overrides.
    """
    groq_label = (groq_label or "").strip().lower()
    if groq_label not in LABELS:
        return consensus
    try:
        conf = max(0.0, min(1.0, float(groq_confidence)))
    except (TypeError, ValueError):
        conf = 0.0

    agrees = groq_label == consensus.get("label")
    record = {
        "label": groq_label,
        "confidence": round(conf, 4),
        "agrees": agrees,
        "reason": str(groq_reason or "")[:600],
        "quotes": [str(q)[:200] for q in (groq_quotes or [])[:3]],
        "model": model_used,
        "overrode": False,
    }

    if agrees:
        consensus["confidence"] = round(min(0.99, consensus["confidence"] + 0.10 * conf), 4)
    elif conf >= GROQ_OVERRIDE_CONFIDENCE:
        consensus["label"] = groq_label
        # Capped at the same 0.99 every other path uses. An LLM's self-reported
        # certainty is not a calibrated probability — it returns a round 1.0
        # readily — and writing it through verbatim produced stored rows at
        # confidence 1.00 and score ±1.000 exactly: a maximally extreme reading
        # asserted with more certainty than the ensemble can express anywhere
        # else. `combine()` caps for exactly this reason; the override was the
        # one path that skipped it.
        confidence = min(0.99, conf)
        score = SENT_VALUE[groq_label] * confidence

        # Re-apply the context calibration. It was computed against this post's
        # text and account, so it holds no matter which model produced the
        # label — but it used to be dropped on override, leaving the evidence
        # drawer showing "irony cue -0.10" beside a number that adjustment had
        # never touched. Reasoning on display has to be reasoning that ran.
        adjustments = consensus.get("context_adjustments") or []
        if adjustments:
            delta = sum(a["delta"] for a in adjustments)
            confidence = max(0.05, min(0.99, confidence + delta))
            score *= max(0.55, 1.0 + min(0.0, delta))

        consensus["confidence"] = round(confidence, 4)
        consensus["score"] = round(max(-1.0, min(1.0, score)), 3)
        consensus["chosen_by"] = f"Groq final check ({model_used or 'llm'}) — overrode {consensus['agreement']} model consensus"
        record["overrode"] = True
    else:
        # dissent that is not confident enough to act on still costs certainty
        consensus["confidence"] = round(max(0.05, consensus["confidence"] - 0.08), 4)

    consensus["groq_check"] = record
    # legacy keys the drawer and older rows still read
    consensus["groq_sentiment"] = groq_label
    consensus["groq_agrees"] = agrees
    return consensus


# ── evidence provenance ─────────────────────────────────────────────────────

def build_evidence(consensus: dict, *, lexicon_terms: list[dict] | None = None,
                   mctx: MetaContext | None = None,
                   score_parts: list[dict] | None = None,
                   fact_check: dict | None = None) -> list[dict]:
    """Assemble "where this verdict came from", one entry per source.

    This is what the post drawer renders under *Evidence*. Every entry names a
    concrete source — a model, the account metadata, the engagement numbers, or
    a named news API — so nothing in the verdict is unattributed.
    """
    ev: list[dict] = []

    for v in consensus.get("votes", []):
        model = v.get("model", "")
        items = []
        if model == "lexicon" and lexicon_terms:
            items = [
                f"“{t['term']}” → {t['polarity']}"
                + (f" ({'; '.join(t['rules'])})" if t.get("rules") else "")
                for t in lexicon_terms[:6]
            ]
        elif v.get("probs"):
            items = [f"{l}: {v['probs'].get(l, 0):.0%}" for l in LABELS if l in v["probs"]]
        ev.append({
            "source": f"Model — {model}",
            "kind": "model",
            "detail": MODEL_DESCRIPTIONS.get(model, ""),
            "verdict": f"{v.get('label')} at {v.get('confidence', 0):.0%} confidence",
            "items": items,
        })

    groq = consensus.get("groq_check")
    if groq:
        groq_model = groq.get("model") or ""
        ev.append({
            "source": "Groq LLM final check" + (f" — {groq_model}" if groq_model else ""),
            "kind": "llm",
            "detail": MODEL_DESCRIPTIONS["groq"],
            "verdict": (f"{groq['label']} at {groq['confidence']:.0%} — "
                        + ("overrode the model consensus" if groq.get("overrode")
                           else "agrees" if groq.get("agrees") else "dissents (not acted on)")),
            "items": [f"“{q}”" for q in groq.get("quotes", [])]
                     + ([groq["reason"]] if groq.get("reason") else []),
        })

    if consensus.get("context_adjustments"):
        ev.append({
            "source": "Context signals",
            "kind": "context",
            "detail": "Discourse structure of the post and the account that wrote it",
            "verdict": f"{len(consensus['context_adjustments'])} adjustment(s) to confidence",
            "items": [f"{a['factor']} ({a['delta']:+.2f}) — {a['reason']}"
                      for a in consensus["context_adjustments"]],
        })

    if mctx is not None:
        ev.append({
            "source": "Account & engagement metadata",
            "kind": "metadata",
            "detail": f"Collected from {mctx.platform or 'the platform'} alongside the post",
            "verdict": f"@{mctx.author_handle or 'unknown'}"
                       + (" · verified" if mctx.author_verified else "")
                       + (" · amplification burst" if mctx.is_amplified else ""),
            "items": [
                f"{mctx.author_followers:,} followers",
                f"account age {mctx.author_account_age_days} days",
                "engagement " + ", ".join(f"{k} {v:,}" for k, v in (mctx.engagement or {}).items())
                if mctx.engagement else "no engagement data",
            ],
        })

    if score_parts:
        ev.append({
            "source": "Concern score breakdown",
            "kind": "score",
            "detail": "How the 0-100 number was assembled from its four inputs",
            "verdict": f"{sum(p['points'] for p in score_parts):.0f} / 100",
            "items": [f"{p['factor']}: {p['points']:.1f} pts (weight {p['weight']:.0%}, "
                      f"input {p['input']}) — {p['detail']}" for p in score_parts],
        })

    if fact_check and fact_check.get("checked"):
        for source in fact_check.get("sources", []) or []:
            arts = [m for m in (fact_check.get("matches") or [])
                    if not m.get("api") or m.get("api") == source]
            ev.append({
                "source": f"News corroboration — {source}",
                "kind": "news",
                "detail": f"Independent reporting searched for “{fact_check.get('query', '')}”",
                "verdict": fact_check.get("verdict", ""),
                "items": [f"{m.get('source', '')} — {m.get('title', '')}" for m in arts[:5]]
                         or ["no matching articles"],
                "links": [{"title": m.get("title", ""), "link": m.get("link", ""),
                           "source": m.get("source", "")} for m in arts[:5]],
            })

    return ev
