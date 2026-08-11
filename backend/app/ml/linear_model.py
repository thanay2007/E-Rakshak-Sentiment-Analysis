# -*- coding: utf-8 -*-
"""Model #2 of the ensemble — TF-IDF (word 1-2 + char 2-5) + LinearSVC.

A genuinely different modelling approach from the MuRIL transformer: a linear
classifier over sparse n-gram features, trained on the SAME corpus so the two
are directly comparable (see baseline_report.json).

Char n-grams (2-5) are what let a linear model cope with Hinglish/Gujlish
spelling variation ("bahut / bhut / bohot") — the reason a classical model
stays competitive on code-mixed Indian text.

**Context awareness.** The model is trained and served on
`ml.context.model_input(text)`, i.e. the post prefixed with its discourse tags
(`[ctx1 q self short] …`). Those tags are ordinary tokens to the vectorizer, so
the word n-gram features include them and the linear weights learn things like
"`rep` co-occurring with a negative term predicts neutral more often than
negative" — a burner-account rant and a news desk relaying that rant stop
looking identical. Because `model_input` is applied identically in
train_baseline.py and here, there is no train/serve skew.

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
from app.ml.context import CONTEXT_PREFIX_VERSION, TextContext, model_input

log = logging.getLogger("sentinel.ml")

MODEL_DIR = settings.MODELS_DIR / "sentiment-linear"
MODEL_PATH = MODEL_DIR / "model.joblib"

LABELS = ("negative", "neutral", "positive")

_model = None       # (vectorizer, classifier) once loaded
_artifact_ctx = ""  # context version the loaded artifact was trained with


def _softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    exps = [math.exp(x - m) for x in xs]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def load() -> object | None:
    """Load the saved (vectorizer, clf). Returns None if not trained yet.

    Artifacts are versioned by the context-prefix scheme they were trained
    under. An artifact saved before the prefix existed is a bare 2-tuple; it
    still loads and still predicts, but it is served RAW TEXT rather than the
    prefixed input, because feeding it tokens it never saw in training is a
    silent distribution shift — the model would keep answering, just worse,
    which is the failure mode hardest to notice. The warning names the fix.
    """
    global _model, _artifact_ctx
    if _model is not None:
        return _model
    if not MODEL_PATH.exists():
        return None
    try:
        import joblib

        blob = joblib.load(MODEL_PATH)
        if isinstance(blob, dict):
            _model = (blob["vectorizer"], blob["classifier"])
            _artifact_ctx = blob.get("context_version", "")
        else:  # legacy 2-tuple, pre-context
            _model = blob
            _artifact_ctx = ""
        if _artifact_ctx != CONTEXT_PREFIX_VERSION:
            log.warning(
                "Classical sentiment model at %s was trained without the "
                "current context prefix (artifact=%r, expected=%r). Serving it "
                "on raw text so its predictions stay valid — retrain with "
                "`python -m app.ml.train_baseline` to make it context-aware.",
                MODEL_PATH, _artifact_ctx or "none", CONTEXT_PREFIX_VERSION)
        else:
            log.info("Loaded context-aware classical sentiment model from %s", MODEL_PATH)
        return _model
    except Exception as exc:  # pragma: no cover
        log.warning("Classical model load failed (%s)", exc)
        return None


def context_version() -> str:
    """Which context scheme the loaded artifact was trained under ("" = none)."""
    load()
    return _artifact_ctx


def available() -> bool:
    return load() is not None


def predict_batch(texts: list[str],
                  contexts: list[TextContext] | None = None) -> list[dict] | None:
    """Per-text {label, confidence, probs} or None if the model isn't trained.

    `texts` are RAW post texts — the context prefix is applied here so callers
    cannot accidentally skip it and silently shift the input distribution.
    """
    model = load()
    if model is None:
        return None
    vec, clf = model
    if _artifact_ctx != CONTEXT_PREFIX_VERSION:
        prepared = list(texts)          # pre-context artifact — raw text only
    elif contexts is not None:
        prepared = [model_input(t, c) for t, c in zip(texts, contexts)]
    else:
        prepared = [model_input(t) for t in texts]
    X = vec.transform(prepared)
    margins = clf.decision_function(X)  # (n, n_classes) one-vs-rest scores
    classes = [str(c) for c in clf.classes_]
    out = []
    for row in margins:
        row = list(row)
        probs_list = _softmax(row)
        probs = {classes[i]: round(probs_list[i], 4) for i in range(len(classes))}
        for l in LABELS:
            probs.setdefault(l, 0.0)
        label = max(LABELS, key=lambda l: probs[l])
        out.append({"label": label, "confidence": round(probs[label], 4),
                    "probs": {l: probs[l] for l in LABELS}})
    return out


def save(vectorizer, classifier) -> None:
    """Persist a fitted (vectorizer, classifier) pair for inference.

    Stamped with the context-prefix version it was trained under, so a future
    change to the prefix scheme is detected at load time instead of quietly
    shifting what the model is served.
    """
    import joblib

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"vectorizer": vectorizer, "classifier": classifier,
                 "context_version": CONTEXT_PREFIX_VERSION}, MODEL_PATH)
    log.info("Saved classical sentiment model (%s) -> %s",
             CONTEXT_PREFIX_VERSION, MODEL_PATH)
