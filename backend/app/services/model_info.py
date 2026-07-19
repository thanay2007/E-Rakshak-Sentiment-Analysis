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
    threat = _load("eval_report.json")               # MuRIL transformer (threat)

    from app.ml import linear_model
    from app.ml.transformer_engine import FINE_TUNED_SENT_DIR

    ensemble = [
        {
            "id": "transformer",
            "name": "MuRIL Transformer",
            "family": "Deep learning (fine-tuned)",
            "base_model": sent_tf.get("model", "google/muril-base-cased"),
            "approach": "12-layer BERT pre-trained on 17 Indian languages, fine-tuned "
                        "as a 3-class sentiment head. Understands context, negation and "
                        "code-mixing the way a rule model cannot.",
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
                        "spelling variants (bahut/bhut/bohot). Fast, interpretable, no GPU.",
            "training_data": {
                "train_rows": baseline.get("train_size"),
                "test_rows": baseline.get("test_size"),
                "sources": "Identical corpus to the transformer — trained head-to-head so "
                           "the accuracy delta is a fair measure of what deep learning buys.",
            },
            "accuracy": baseline.get("overall", {}),
            "per_language": baseline.get("per_language", {}),
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
                        "Fully transparent — every score traces to matched words.",
            "training_data": {
                "train_rows": 0, "test_rows": 0,
                "sources": "No training — hand-curated valence lexicons per language.",
            },
            "accuracy": {},
            "per_language": {},
            "live": True,
            "strength": "Zero-shot, explainable, catches slang the trained models miss.",
        },
    ]

    return {
        "ensemble": {
            "task": "sentiment",
            "decision_rule": "Each model votes a label + confidence. If ≥2 agree, majority "
                             "wins (confidence averaged, +consensus bonus); if all disagree, "
                             "the single most-confident model is chosen. Groq then "
                             "independently double-checks the winning label.",
            "models": ensemble,
        },
        "threat_model": {
            "id": "threat-transformer",
            "name": "MuRIL Threat Classifier",
            "family": "Deep learning (fine-tuned)",
            "labels": ["Incitement to Violence", "Inflammatory", "Fake News", "Neutral"],
            "approach": "Same MuRIL base fine-tuned on a curated 4-category threat dataset; "
                        "backed by the lexicon threat layer and Groq verification.",
            "accuracy": {"accuracy": threat.get("accuracy"), "macro_f1": threat.get("macro_f1")},
            "per_class": threat.get("per_class", {}),
            "eval_samples": threat.get("samples"),
        },
        "verification": {
            "layer": "Groq LLM (llama-3.3-70b)",
            "role": "Independent second opinion on every risky/consensus prediction — "
                    "agreement strengthens confidence, confident disagreement overrides.",
        },
    }
