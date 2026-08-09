"""Full-mode NLP engine — transformer models, loaded once (singleton) at first use.

Model stack (all swappable via the constants below):
  • Threat classification: the fine-tuned model saved by ml/train.py
    (google/muril-base-cased or xlm-roberta-base head) if present in
    ml/models/threat-classifier/, otherwise zero-shot
    joeddav/xlm-roberta-large-xnli with the 4 SENTINEL labels as candidates.
  • Sentiment: cardiffnlp/twitter-xlm-roberta-base-sentiment
  • Toxicity:  unitary/multilingual-toxic-xlm-roberta (fallback: keep lite toxicity)

Everything degrades gracefully: any load/inference failure falls back to the
lite engine, so NLP_MODE=full can never break the demo. Batched inference via
the HF pipeline batch API; keep LIGHTWEIGHT=true semantics by simply staying
in lite mode on low-resource machines.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.ml.device import get_device

log = logging.getLogger("sentinel.ml")

ZERO_SHOT_MODEL = "joeddav/xlm-roberta-large-xnli"
SENTIMENT_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
TOXICITY_MODEL = "unitary/multilingual-toxic-xlm-roberta"
FINE_TUNED_DIR = settings.MODELS_DIR / "threat-classifier"
FINE_TUNED_SENT_DIR = settings.MODELS_DIR / "sentiment-classifier"

CANDIDATE_LABELS = ["Incitement to Violence", "Inflammatory", "Fake News", "Neutral"]
# Hypothesis phrasing helps XNLI zero-shot a lot for this domain:
HYPOTHESIS = "This social media post is {}."

_engine: "TransformerEngine | None" = None


class TransformerEngine:
    def __init__(self) -> None:
        import os
        if getattr(settings, "HF_TOKEN", ""):
            os.environ.setdefault("HF_TOKEN", settings.HF_TOKEN)
            os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", settings.HF_TOKEN)
        # Suppress informational unauthenticated warning from HF Hub
        logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)

        from transformers import pipeline as hf_pipeline  # heavy import, deferred

        device = get_device()
        self.device = device
        log.info("Loading transformer models on device: %s", device)

        self.fine_tuned = FINE_TUNED_DIR.exists()
        if self.fine_tuned:
            log.info("Loading fine-tuned threat classifier from %s", FINE_TUNED_DIR)
            self.clf = hf_pipeline("text-classification", model=str(FINE_TUNED_DIR),
                                   tokenizer=str(FINE_TUNED_DIR), top_k=None, truncation=True,
                                   device=device)
        else:
            log.info("Loading zero-shot classifier %s", ZERO_SHOT_MODEL)
            self.clf = hf_pipeline("zero-shot-classification", model=ZERO_SHOT_MODEL, truncation=True,
                                   device=device)

        # Prefer the MuRIL sentiment head fine-tuned by ml/train_sentiment.py on
        # real en/hi/gu/Hinglish/Gujlish corpora; fall back to the generic
        # cardiffnlp multilingual model when no fine-tune has been run yet.
        if FINE_TUNED_SENT_DIR.exists():
            log.info("Loading fine-tuned sentiment model from %s", FINE_TUNED_SENT_DIR)
            self.sent = hf_pipeline("text-classification", model=str(FINE_TUNED_SENT_DIR),
                                    tokenizer=str(FINE_TUNED_SENT_DIR), top_k=None, truncation=True,
                                    device=device)
        else:
            self.sent = hf_pipeline("text-classification", model=SENTIMENT_MODEL, top_k=None, truncation=True,
                                    device=device)
        try:
            self.tox = hf_pipeline("text-classification", model=TOXICITY_MODEL, top_k=None, truncation=True,
                                   device=device)
        except Exception:  # model optional
            log.warning("Toxicity model unavailable; lite toxicity stays active")
            self.tox = None

    # ── classification ────────────────────────────────────────────────────
    def classify_batch(self, texts: list[str]) -> list[dict]:
        if self.fine_tuned:
            outs = self.clf(texts, batch_size=16)
            results = []
            for scores in outs:
                probs = {d["label"]: round(d["score"], 4) for d in scores}
                label = max(probs, key=probs.get)
                results.append({"label": label, "confidence": probs[label], "probs": probs})
            return results
        outs = self.clf(texts, CANDIDATE_LABELS, hypothesis_template=HYPOTHESIS,
                        multi_label=False, batch_size=8)
        if isinstance(outs, dict):
            outs = [outs]
        return [
            {
                "label": o["labels"][0],
                "confidence": round(o["scores"][0], 4),
                "probs": {l: round(s, 4) for l, s in zip(o["labels"], o["scores"])},
            }
            for o in outs
        ]

    def sentiment_batch(self, texts: list[str]) -> list[tuple[str, float]]:
        return [(v["label"], v["value"]) for v in self.sentiment_votes_batch(texts)]

    def sentiment_votes_batch(self, texts: list[str]) -> list[dict]:
        """Richer sentiment output for the ensemble: label, numeric value
        [-1,1], winning-class confidence, and full per-class probabilities."""
        outs = self.sent(texts, batch_size=16)
        results = []
        for scores in outs:
            by = {d["label"].lower(): d["score"] for d in scores}
            value = by.get("positive", 0) - by.get("negative", 0)  # [-1, 1]
            label = max(by, key=by.get)
            results.append({
                "label": label,
                "value": round(value, 3),
                "confidence": round(by[label], 4),
                "probs": {k: round(v, 4) for k, v in by.items()},
            })
        return results

    def toxicity_batch(self, texts: list[str]) -> list[float] | None:
        if self.tox is None:
            return None
        outs = self.tox(texts, batch_size=16)
        results = []
        for scores in outs:
            toxic = max((d["score"] for d in scores if "toxic" in d["label"].lower()), default=0.0)
            results.append(round(toxic, 3))
        return results


def get_engine() -> TransformerEngine | None:
    """Singleton loader. Returns None (→ lite fallback) if the ML stack is missing."""
    global _engine
    if _engine is not None:
        return _engine
    try:
        _engine = TransformerEngine()
        log.info("Transformer engine ready (fine-tuned=%s)", _engine.fine_tuned)
    except Exception as exc:
        log.warning("NLP_MODE=full requested but transformer stack unavailable (%s). "
                    "Falling back to lite engine.", exc)
        _engine = None
    return _engine
