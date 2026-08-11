# -*- coding: utf-8 -*-
"""Model registry — structured metadata for the 3-model consensus ensemble,
read from the real evaluation reports produced during training.

Exposed at /api/models so the portal (and the mentor) can see, live, exactly
what each model is, what data trained it, and how accurate it measured — no
hand-typed numbers, the figures come straight from the eval report JSONs.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.ml.context import CONTEXT_PREFIX_VERSION
from app.ml.ensemble import GROQ_OVERRIDE_CONFIDENCE
from app.ml.score import FORMULA

_ML = settings.MODELS_DIR.parent  # backend/app/ml (MODELS_DIR = app/ml/models)


def _load(name: str) -> dict:
    p = _ML / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_models() -> dict:
    sent_tf = _load("sentiment_eval_report.json")   # MuRIL transformer (sentiment)
    baseline = _load("baseline_report.json")         # TF-IDF + LinearSVC (sentiment)
    pipeline_eval = _load("eval_report.json")        # end-to-end pipeline metrics

    from app.ml import linear_model
    from app.ml.transformer_engine import FINE_TUNED_SENT_DIR

    ensemble = [
        {
            "id": "transformer",
            "name": "MuRIL Transformer",
            "family": "Deep learning (fine-tuned)",
            "base_model": sent_tf.get("model", "google/muril-base-cased"),
            "approach": "12-layer BERT pre-trained on 17 Indian languages, fine-tuned "
                        "as a 3-class sentiment head. Reads the post together with its "
                        "discourse tags (question, reported speech, irony, contrast), so "
                        "it conditions on structure rather than words alone.",
            "training_data": {
                "train_rows": sent_tf.get("train_size"),
                "test_rows": sent_tf.get("test_size"),
                "sources": "22 public datasets (Kaggle + HuggingFace): English, Hindi, "
                           "Gujarati, Hinglish & Gujlish social-media text, plus "
                           "LLM-augmented minority-class examples.",
            },
            "accuracy": sent_tf.get("overall", {}),
            "per_language": sent_tf.get("per_language", {}),
            "epochs": sent_tf.get("epochs"),
            "context_version": sent_tf.get("context_version", ""),
            "context_aware": bool(sent_tf.get("context_version")),
            "live": FINE_TUNED_SENT_DIR.exists(),
            "strength": "Highest overall accuracy; best on native-script Gujarati/Gujlish.",
        },
        {
            "id": "classical",
            "name": "TF-IDF + LinearSVC",
            "family": "Classical machine learning",
            "base_model": baseline.get("model", "tfidf(word1-2 + char2-5) + LinearSVC"),
            "approach": "Linear support-vector classifier over TF-IDF word (1-2) and "
                        "character (2-5) n-grams. The char n-grams absorb Hinglish/Gujlish "
                        "spelling variants (bahut/bhut/bohot). The discourse tags enter as "
                        "n-gram features too. Fast, interpretable, no GPU.",
            "training_data": {
                "train_rows": baseline.get("train_size"),
                "test_rows": baseline.get("test_size"),
                "sources": "Identical corpus to the transformer — trained head-to-head so "
                           "the accuracy delta is a fair measure of what deep learning buys.",
            },
            "accuracy": baseline.get("overall", {}),
            "per_language": baseline.get("per_language", {}),
            "context_version": linear_model.context_version(),
            "context_aware": bool(linear_model.context_version()),
            "live": linear_model.available(),
            "strength": "Robust to spelling noise; a strong, cheap second opinion.",
        },
        {
            "id": "lexicon",
            "name": "Multilingual Lexicon (VADER-style)",
            "family": "Rule-based",
            "base_model": "valence lexicon + negation/booster heuristics",
            "approach": "Ported from cjhutto/vaderSentiment and extended to Hindi, "
                        "Gujarati, Hinglish & Gujlish: negation flips valence, "
                        "boosters/dampeners scale it, caps and punctuation intensify. "
                        "Adds contrast resolution (the clause after 'but' is the author's "
                        "position), irony inversion, and damping of reported or "
                        "hypothetical valence. Fully transparent — every score traces to "
                        "the matched word and the rule that modified it.",
            "training_data": {
                "train_rows": 0, "test_rows": 0,
                "sources": "No training — hand-curated valence lexicons per language.",
            },
            "accuracy": {},
            "per_language": {},
            "context_version": "built-in",
            "context_aware": True,
            "live": True,
            "strength": "Zero-shot, explainable, catches slang the trained models miss.",
        },
    ]

    return {
        "ensemble": {
            "task": "sentiment",
            "labels": ["negative", "neutral", "positive"],
            "decision_rule": "Each model votes a label + confidence. If ≥2 agree, majority "
                             "wins (confidence averaged, +consensus bonus); if all disagree, "
                             "the single most-confident model is chosen. Account and reach "
                             "context then adjusts confidence only — never the label — and "
                             "each adjustment is recorded with a reason. Groq reads the post "
                             "last and can overturn the result when it is confident.",
            "context": {
                "version": CONTEXT_PREFIX_VERSION,
                "textual": "Discourse tags derived from the text alone (question, reported "
                           "speech, conditional, irony cue, contrast, first-person, "
                           "emphasis, length) are prepended to the model input at TRAINING "
                           "and inference alike, so the models learn to condition on them.",
                "metadata": "Account standing, reach, amplification and platform adjust the "
                            "ensemble's confidence after the vote, bounded and always with "
                            "a stated reason.",
            },
            "models": ensemble,
        },
        "final_check": {
            "layer": f"Groq LLM ({settings.GROQ_MODEL})",
            "role": "Reads the post independently after the three models and is the last "
                    "word: agreement raises confidence, an unconfident dissent lowers it, "
                    "and a dissent at or above "
                    f"{GROQ_OVERRIDE_CONFIDENCE:.0%} confidence replaces the label and is "
                    "recorded as an override.",
            "enabled": bool(settings.GROQ_API_KEY),
        },
        "pipeline_eval": {
            "accuracy": pipeline_eval.get("accuracy"),
            "macro_f1": pipeline_eval.get("macro_f1"),
            "per_class": pipeline_eval.get("per_class", {}),
            "samples": pipeline_eval.get("samples"),
        },
        "scoring": {
            "name": "Concern score",
            "range": "0-100",
            "formula": FORMULA,
            "note": "Derived from sentiment, not from a threat category. Weighted so no "
                    "single dimension reaches an alert band alone.",
        },
    }
