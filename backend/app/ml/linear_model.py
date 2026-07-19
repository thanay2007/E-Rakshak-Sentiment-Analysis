# -*- coding: utf-8 -*-
"""Classical ML sentiment model — TF-IDF (word 1-2 + char 2-5) + LinearSVC.

This is model #2 of the 3-model consensus ensemble (ml/ensemble.py). It is a
genuinely different modelling approach from the MuRIL transformer: a linear
classifier over sparse n-gram features, trained on the SAME 48,774-row corpus
so the two are directly comparable (see baseline_report.json).

Char n-grams (2-5) are what let a linear model cope with Hinglish/Gujlish
spelling variation ("bahut / bhut / bohot") — the reason a classical model
stays competitive on code-mixed Indian text.

LinearSVC has no predict_proba; we turn its decision-function margins into a
calibrated confidence via a softmax over the one-vs-rest scores. That gives the
ensemble a per-model confidence to weigh, exactly like the transformer's.

Train + save (from backend/):  python -m app.ml.train_baseline
Artifact: ml/models/sentiment-linear/model.joblib
"""
from __future__ import annotations

import logging
import math

from app.config import settings

log = logging.getLogger("sentinel.ml")

MODEL_DIR = settings.MODELS_DIR / "sentiment-linear"
MODEL_PATH = MODEL_DIR / "model.joblib"

LABELS = ("negative", "neutral", "positive")

_model = None  # (vectorizer, classifier) tuple once loaded


def _softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    exps = [math.exp(x - m) for x in xs]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def load() -> object | None:
    """Load the saved (vectorizer, clf). Returns None if not trained yet."""
    global _model
    if _model is not None:
        return _model
    if not MODEL_PATH.exists():
        return None
    try:
        import joblib

        _model = joblib.load(MODEL_PATH)
        log.info("Loaded classical sentiment model from %s", MODEL_PATH)
        return _model
    except Exception as exc:  # pragma: no cover
        log.warning("Classical model load failed (%s)", exc)
        return None


def available() -> bool:
    return load() is not None


def predict_batch(texts: list[str]) -> list[dict] | None:
    """Per-text {label, confidence, probs} or None if the model isn't trained."""
    model = load()
    if model is None:
        return None
    vec, clf = model
    X = vec.transform(texts)
    margins = clf.decision_function(X)  # (n, n_classes) one-vs-rest scores
    classes = [str(c) for c in clf.classes_]
    out = []
    for row in margins:
        row = list(row)
        probs_list = _softmax(row)
        probs = {classes[i]: round(probs_list[i], 4) for i in range(len(classes))}
        label = max(probs, key=probs.get)
        out.append({"label": label, "confidence": round(probs[label], 4), "probs": probs})
    return out


def save(vectorizer, classifier) -> None:
    """Persist a fitted (vectorizer, classifier) pair for inference."""
    import joblib

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump((vectorizer, classifier), MODEL_PATH)
    log.info("Saved classical sentiment model -> %s", MODEL_PATH)
