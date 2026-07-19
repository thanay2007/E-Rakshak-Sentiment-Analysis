"""NLP pipeline orchestrator.

One entry point — enrich(raw) / enrich_batch(raws) — used by ingestion,
seeding and evaluation. Chooses the engine by NLP_MODE:

  lite (default): normalization → language ID → lexicon classifier →
                  sentiment → toxicity → threat score. Zero downloads.
  full:           transformer engine for classification/sentiment/toxicity;
                  language ID, intent, evidence terms and the threat-score
                  formula stay shared. Falls back to lite per-call on failure.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.ml.classifier import classify
from app.ml.language import detect_language
from app.ml.sentiment import analyze_sentiment
from app.ml.threat_score import threat_score
from app.ml.toxicity import analyze_toxicity
from app.schemas import RawPost

log = logging.getLogger("sentinel.ml")


class NLPPipeline:
    def __init__(self) -> None:
        self.mode = settings.NLP_MODE
        self._engine = None
        if self.mode == "full":
            from app.ml.transformer_engine import get_engine

            self._engine = get_engine()
            if self._engine is None:
                self.mode = "lite"

    # ── single post ───────────────────────────────────────────────────────
    def enrich(self, raw: RawPost) -> dict:
        return self.enrich_batch([raw])[0]

    # ── batched (used by seeding / evaluation / burst ingestion) ─────────
    def enrich_batch(self, raws: list[RawPost]) -> list[dict]:
        from app.ml.slang import translate_slang
        from app.ml import ensemble, linear_model
        texts = [translate_slang(r.text) for r in raws]
        lite = [classify(t) for t in texts]  # always run: supplies intent/evidence/signals

        # ── sentiment model #1 (transformer) + threat/toxicity, full mode ──
        sent_tf = None
        if self.mode == "full" and self._engine is not None:
            try:
                cls = self._engine.classify_batch(texts)
                sent_tf = self._engine.sentiment_votes_batch(texts)
                toxs = self._engine.toxicity_batch(texts)
            except Exception as exc:
                log.warning("Transformer inference failed (%s); lite fallback for this batch", exc)
                cls = toxs = None
        else:
            cls = toxs = None

        # ── sentiment model #2 (classical TF-IDF + LinearSVC) ──────────────
        sent_lin = linear_model.predict_batch(texts)  # None if not trained

        out = []
        for i, raw in enumerate(raws):
            lang, mixed = detect_language(raw.text)
            c = cls[i] if cls else {k: lite[i][k] for k in ("label", "confidence", "probs")}
            signals = lite[i]["signals"]

            # ── 3-model sentiment consensus ────────────────────────────────
            votes = []
            if sent_tf:
                v = sent_tf[i]
                votes.append({"model": "transformer", "label": v["label"],
                              "confidence": v["confidence"], "probs": v["probs"]})
            if sent_lin:
                v = sent_lin[i]
                votes.append({"model": "classical", "label": v["label"],
                              "confidence": v["confidence"], "probs": v["probs"]})
            # lexicon vote (rule-based) — confidence from valence magnitude
            lex_label, lex_val = analyze_sentiment(raw.text, signals)
            votes.append({"model": "lexicon", "label": lex_label,
                          "confidence": round(min(0.95, 0.45 + abs(lex_val) * 0.55), 4),
                          "probs": {}})
            consensus = ensemble.combine(votes)
            s_label, s_score = consensus["label"], consensus["score"]

            tox_lite, flags = analyze_toxicity(signals)
            tox = toxs[i] if toxs else tox_lite

            score = threat_score(
                label=c["label"], confidence=c["confidence"], toxicity=tox,
                engagement=raw.engagement, is_amplified=raw.is_amplified,
                keyword_severity=lite[i]["keyword_severity"],
            )

            out.append({
                "language": lang,
                "code_mixed": mixed,
                "sentiment_label": s_label,
                "sentiment_score": s_score,
                "sentiment_consensus": consensus,   # 3-model votes + chosen_by
                "intent": lite[i]["intent"],
                "threat_label": c["label"],
                "threat_confidence": round(c["confidence"], 4),
                "class_probs": c["probs"],
                "hate_flags": flags,
                "toxicity_score": tox,
                "threat_score": score,
                "keywords": lite[i]["matched_terms"],
            })
        return out


_pipeline: NLPPipeline | None = None


def get_pipeline() -> NLPPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = NLPPipeline()
        log.info("NLP pipeline ready (mode=%s)", _pipeline.mode)
    return _pipeline
