"""Model #1 of the ensemble — the transformer stack, loaded once at first use.

Model stack:
  • Sentiment: the MuRIL head fine-tuned by ml/train_sentiment.py if present in
    ml/models/sentiment-classifier/, otherwise the generic
    cardiffnlp/twitter-xlm-roberta-base-sentiment.
  • Toxicity:  unitary/multilingual-toxic-xlm-roberta (optional — falls back to
    the lite toxicity heuristic when unavailable).

The four-class threat classifier that used to live here is gone. A sentiment
model has no basis for asserting that a post *is* incitement or *is* fake news;
those are investigative conclusions, not properties of the text's tone. What
remains is the judgement the model can actually defend: how positive or
negative the post is, and how abusive its language is.

**Context awareness.** `sentiment_votes_batch` is fed
`ml.context.model_input(text)` — the post prefixed with its discourse tags —
which is exactly what train_sentiment.py trains on. MuRIL sees the tags as
tokens and attends over them like any other, so "[ctx1 rep cond long]" shifts
the representation of a relayed hypothetical away from a first-person assertion
carrying the same words.

Everything degrades gracefully: any load/inference failure falls back to the
lite engine, so NLP_MODE=full can never break the console.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.ml.context import CONTEXT_PREFIX_VERSION, TextContext, model_input
from app.ml.device import get_device

log = logging.getLogger("sentinel.ml")

SENTIMENT_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
TOXICITY_MODEL = "unitary/multilingual-toxic-xlm-roberta"
FINE_TUNED_SENT_DIR = settings.MODELS_DIR / "sentiment-classifier"

LABELS = ("negative", "neutral", "positive")
# cardiffnlp emits LABEL_0/1/2; the fine-tune emits the words. Normalize both.
_ALIASES = {
    "label_0": "negative", "label_1": "neutral", "label_2": "positive",
    "neg": "negative", "neu": "neutral", "pos": "positive",
}

_engine: "TransformerEngine | None" = None


def _canon(label: str) -> str:
    l = label.strip().lower()
    return _ALIASES.get(l, l)


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

        # Prefer the MuRIL sentiment head fine-tuned by ml/train_sentiment.py on
        # real en/hi/gu/Hinglish/Gujlish corpora; fall back to the generic
        # cardiffnlp multilingual model when no fine-tune has been run yet.
        self.fine_tuned = FINE_TUNED_SENT_DIR.exists()
        # Which context scheme the checkpoint was fine-tuned under. Written by
        # train_sentiment.py; absent on a checkpoint from before the prefix
        # existed, which is then served raw text — see `_prepare`.
        self.context_version = ""
        marker = FINE_TUNED_SENT_DIR / "sentinel_context.json"
        if marker.exists():
            try:
                import json
                self.context_version = json.loads(
                    marker.read_text(encoding="utf-8")).get("context_version", "")
            except Exception:
                self.context_version = ""
        if self.fine_tuned and self.context_version != CONTEXT_PREFIX_VERSION:
            log.warning(
                "Fine-tuned sentiment checkpoint at %s predates the current "
                "context prefix (checkpoint=%r, expected=%r). Serving it on raw "
                "text so its predictions stay valid — retrain with "
                "`python -m app.ml.train_sentiment` to make it context-aware.",
                FINE_TUNED_SENT_DIR, self.context_version or "none",
                CONTEXT_PREFIX_VERSION)
        if self.fine_tuned:
            log.info("Loading fine-tuned sentiment model from %s", FINE_TUNED_SENT_DIR)
            self.sent = hf_pipeline("text-classification", model=str(FINE_TUNED_SENT_DIR),
                                    tokenizer=str(FINE_TUNED_SENT_DIR), top_k=None,
                                    truncation=True, device=device)
        else:
            log.info("No fine-tune on disk — serving %s", SENTIMENT_MODEL)
            self.sent = hf_pipeline("text-classification", model=SENTIMENT_MODEL,
                                    top_k=None, truncation=True, device=device)
        try:
            self.tox = hf_pipeline("text-classification", model=TOXICITY_MODEL,
                                   top_k=None, truncation=True, device=device)
        except Exception:  # model optional
            log.warning("Toxicity model unavailable; lite toxicity stays active")
            self.tox = None

    # ── sentiment ─────────────────────────────────────────────────────────
    def _prepare(self, texts: list[str],
                 contexts: list[TextContext] | None) -> list[str]:
        """Render the model input, or pass raw text to a checkpoint that was
        never trained on the prefix (the generic cardiffnlp model included —
        it has no idea what `[ctx1 q self short]` means)."""
        if not self.fine_tuned or self.context_version != CONTEXT_PREFIX_VERSION:
            return list(texts)
        if contexts is not None:
            return [model_input(t, c) for t, c in zip(texts, contexts)]
        return [model_input(t) for t in texts]

    def sentiment_votes_batch(self, texts: list[str],
                              contexts: list[TextContext] | None = None) -> list[dict]:
        """Sentiment for the ensemble: label, numeric value [-1,1], winning-class
        confidence, and full per-class probabilities.

        `texts` are RAW post texts; the context prefix is applied here so the
        served input matches the trained input exactly.
        """
        outs = self.sent(self._prepare(texts, contexts), batch_size=16)
        results = []
        for scores in outs:
            by = {_canon(d["label"]): d["score"] for d in scores}
            for l in LABELS:
                by.setdefault(l, 0.0)
            value = by["positive"] - by["negative"]  # [-1, 1]
            label = max(LABELS, key=lambda l: by[l])
            results.append({
                "label": label,
                "value": round(value, 3),
                "confidence": round(by[label], 4),
                "probs": {l: round(by[l], 4) for l in LABELS},
            })
        return results

    def sentiment_batch(self, texts: list[str]) -> list[tuple[str, float]]:
        return [(v["label"], v["value"]) for v in self.sentiment_votes_batch(texts)]

    def toxicity_batch(self, texts: list[str]) -> list[float] | None:
        if self.tox is None:
            return None
        outs = self.tox(texts, batch_size=16)
        results = []
        for scores in outs:
            toxic = max((d["score"] for d in scores if "toxic" in d["label"].lower()),
                        default=0.0)
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
