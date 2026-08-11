"""NLP pipeline orchestrator.

One entry point — enrich(raw) / enrich_batch(raws) — used by ingestion,
seeding and evaluation. Every post comes out with exactly one tag:
**positive, negative or neutral**, a 0-100 concern score, and the full evidence
trail behind both.

Order of work:
  1. slang normalization, language ID, lexicon signal extraction
  2. context extraction (ml/context.py) — discourse structure from the text,
     account/reach metadata from the post
  3. three independent sentiment models, all fed the same context-tagged input
  4. ensemble: majority, or the best model's answer when all three disagree
  5. context calibration of confidence, with a reason recorded per adjustment
  6. concern score (ml/score.py) from negativity × confidence, toxicity,
     virality and matched-term severity
  7. evidence provenance assembled from every source that contributed

Groq's final check is applied afterwards, in services/groq_verifier.py, because
it is a network call and this function runs on a worker thread inside the
ingest tick.

NLP_MODE picks the engine: `full` adds the fine-tuned MuRIL head and the
toxicity model; `lite` runs the lexicon model alone. Falls back to lite
per-call on any transformer failure.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.ml import ensemble, linear_model
from app.ml.classifier import extract_signals
from app.ml.context import build_text_context, meta_from_raw, model_inputs
from app.ml.language import detect_language
from app.ml.score import concern_score
from app.ml.sentiment import analyze_sentiment
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

        texts = [translate_slang(r.text) for r in raws]
        signals = [extract_signals(t) for t in texts]
        # discourse context, shared by all three models and by the calibration
        _, contexts = model_inputs(texts)

        # ── model #1: fine-tuned MuRIL transformer (full mode only) ─────────
        sent_tf = toxs = None
        if self.mode == "full" and self._engine is not None:
            try:
                sent_tf = self._engine.sentiment_votes_batch(texts, contexts)
                toxs = self._engine.toxicity_batch(texts)
            except Exception as exc:
                log.warning("Transformer inference failed (%s); lite fallback for this batch", exc)
                sent_tf = toxs = None

        # ── model #2: classical TF-IDF + LinearSVC (None if not trained) ────
        sent_lin = linear_model.predict_batch(texts, contexts)

        out = []
        for i, raw in enumerate(raws):
            lang, mixed = detect_language(raw.text)
            tctx = contexts[i]
            mctx = meta_from_raw(raw, language=lang, code_mixed=mixed)
            sig = signals[i]["signals"]

            votes = []
            if sent_tf:
                v = sent_tf[i]
                votes.append(ensemble.vote("transformer", v["label"], v["confidence"], v["probs"]))
            if sent_lin:
                v = sent_lin[i]
                votes.append(ensemble.vote("classical", v["label"], v["confidence"], v["probs"]))

            # ── model #3: context-aware lexicon (always runs) ───────────────
            lex = analyze_sentiment(texts[i], sig, tctx)
            votes.append(ensemble.vote("lexicon", lex["label"], lex["confidence"],
                                       lex["probs"], lex["evidence"]))

            consensus = ensemble.combine(votes, tctx, mctx)

            tox_lite, flags = analyze_toxicity(sig)
            tox = toxs[i] if toxs else tox_lite

            score, score_parts = concern_score(
                sentiment_score=consensus["score"],
                confidence=consensus["confidence"],
                toxicity=tox,
                engagement=raw.engagement,
                is_amplified=raw.is_amplified,
                term_severity=signals[i]["term_severity"],
            )
            consensus["score_breakdown"] = score_parts

            out.append({
                "language": lang,
                "code_mixed": mixed,
                "sentiment_label": consensus["label"],
                "sentiment_score": consensus["score"],
                "sentiment_confidence": consensus["confidence"],
                "sentiment_consensus": consensus,
                "intent": signals[i]["intent"],
                "class_probs": _mean_probs(votes),
                "hate_flags": flags,
                "toxicity_score": tox,
                "concern_score": score,
                "keywords": signals[i]["matched_terms"],
                # Underscore-prefixed keys are pipeline-internal: the later
                # network stages (Groq final check) need the same inputs to
                # recompute the score with the same formula, and ingestion
                # strips them before the row is built.
                "_engagement": raw.engagement or {},
                "_is_amplified": bool(raw.is_amplified),
                "_term_severity": signals[i]["term_severity"],
                "_meta_context": mctx,
            })
        return out


def attach_evidence(nlp: dict) -> None:
    """Rebuild a post's evidence provenance once every stage has contributed.

    Called after the network stages (news corroboration, Groq final check,
    translation) so the evidence block names every source that actually ran —
    including the ones that ran after the models did. Rebuilding rather than
    appending keeps it idempotent: a post that went through the Groq path and a
    post that did not produce the same shape, just different entries.
    """
    consensus = nlp.get("sentiment_consensus")
    if not isinstance(consensus, dict) or not consensus:
        return
    lexicon_terms = next((v.get("evidence") for v in consensus.get("votes", [])
                          if v.get("model") == "lexicon"), None)
    consensus["evidence"] = ensemble.build_evidence(
        consensus,
        lexicon_terms=lexicon_terms,
        mctx=nlp.get("_meta_context"),
        score_parts=consensus.get("score_breakdown"),
        fact_check=nlp.get("fact_check"),
    )


def _mean_probs(votes: list[dict]) -> dict:
    """Ensemble-average probability across the three labels, for the UI bars."""
    acc = {l: 0.0 for l in ensemble.LABELS}
    n = 0
    for v in votes:
        probs = v.get("probs") or {}
        if not all(l in probs for l in ensemble.LABELS):
            continue
        for l in ensemble.LABELS:
            acc[l] += float(probs[l])
        n += 1
    if not n:
        return {}
    return {l: round(acc[l] / n, 4) for l in ensemble.LABELS}


_pipeline: NLPPipeline | None = None


def get_pipeline() -> NLPPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = NLPPipeline()
        log.info("NLP pipeline ready (mode=%s)", _pipeline.mode)
    return _pipeline
