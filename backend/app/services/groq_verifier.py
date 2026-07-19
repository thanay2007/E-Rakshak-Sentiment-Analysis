"""LLM second-opinion layer (Groq API) — double-checks the local model's
threat + sentiment predictions on the posts where being wrong is expensive.

Flow (inside ingest, BEFORE alerts fire):
  1. Select candidates: threat_score above GROQ_VERIFY_MIN_SCORE, or a
     low-confidence classification (< 0.55). Capped per tick to stay well
     inside Groq's free-tier rate limits.
  2. One batched chat-completion (JSON mode) asks the LLM to independently
     label each post: threat category, sentiment, confidence, one-line reason.
  3. Reconcile: agreement raises confidence; a confident disagreement
     (LLM conf >= 0.70) overrides the label/sentiment and the threat score is
     recomputed with the same formula — the override is never silent, the full
     verdict is stored on the post (`llm_verification`) and shown to analysts.

Zero-config safe: without GROQ_API_KEY the layer is disabled and ingest is
untouched. Any API/parse failure degrades to "unverified" — never blocks.
"""
from __future__ import annotations

import json
import logging
import re

from app.config import THREAT_LABELS, settings
from app.ml.threat_score import SEVERITY

log = logging.getLogger("sentinel.groq")

_SYSTEM = (
    "You are a threat-intelligence reviewer for Gujarat police analysts. Your "
    "assessments may be cited in police reports, so every judgement must be "
    "traceable to the text. You will receive social-media posts (English, Hindi, "
    "Gujarati, or romanized Hinglish/Gujlish). For EACH post, independently assess:\n"
    f"- threat_label: exactly one of {THREAT_LABELS}\n"
    "- sentiment: negative | neutral | positive\n"
    "- confidence: 0.0-1.0 (your certainty in threat_label)\n"
    "- evidence: 1-3 EXACT quotes copied verbatim from the post (original script) "
    "that are the strongest basis for your label; [] if the post is benign\n"
    "- reason: 2-3 sentences explaining the label — reference the quoted phrases, "
    "name the rhetorical technique if any (e.g. unattributed claim, call to gather, "
    "communal framing, fear appeal), and state what would be needed to confirm it\n"
    'Reply ONLY with JSON: {"results": [{"id": <post id>, "threat_label": ..., '
    '"sentiment": ..., "confidence": ..., "evidence": [...], "reason": ...}, ...]} — '
    "one entry per post, same ids as given. Judge the text itself; do not assume "
    "unstated context; never invent facts not present in the post."
)


def enabled() -> bool:
    return bool(settings.GROQ_API_KEY)


async def _call_groq(posts: list[dict]) -> list[dict] | None:
    """One batched request. posts: [{"id", "text"}]. Returns parsed results or None."""
    from app.services.groq_client import chat_json

    data, model_used = await chat_json([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": json.dumps(
            {"posts": [{"id": p["id"], "text": p["text"][:600]} for p in posts]},
            ensure_ascii=False)},
    ])
    if data is None:
        log.warning("Groq verify failed on every model in the fallback chain")
        return None
    if model_used and model_used != settings.GROQ_MODEL:
        log.info("Groq verify served by fallback model %s", model_used)
    results = data.get("results", data if isinstance(data, list) else [])
    return results if isinstance(results, list) else None


def _reconcile(nlp: dict, verdict: dict) -> None:
    """Merge one LLM verdict into the pipeline output (mutates nlp)."""
    llm_label = str(verdict.get("threat_label", "")).strip()
    llm_sent = str(verdict.get("sentiment", "")).strip().lower()
    try:
        llm_conf = max(0.0, min(1.0, float(verdict.get("confidence", 0))))
    except (TypeError, ValueError):
        llm_conf = 0.0
    if llm_label not in THREAT_LABELS:
        return

    agrees = llm_label == nlp["threat_label"]
    evidence = verdict.get("evidence")
    record = {
        "model": settings.GROQ_MODEL,
        "llm_threat_label": llm_label,
        "llm_sentiment": llm_sent,
        "llm_confidence": round(llm_conf, 3),
        "evidence": [str(q)[:200] for q in evidence[:3]] if isinstance(evidence, list) else [],
        "reason": str(verdict.get("reason", ""))[:600],
        "verdict": "agrees" if agrees else "disagrees",
        "overridden": False,
    }

    if agrees:
        # independent agreement → strengthen the belief (bounded)
        nlp["threat_confidence"] = round(min(0.99, nlp["threat_confidence"] + 0.10 * llm_conf), 4)
    elif llm_conf >= 0.70:
        # confident disagreement → the LLM wins; rescale the score with the
        # same formula weights so bands stay meaningful
        old_sev = SEVERITY.get(nlp["threat_label"], 0.05)
        new_sev = SEVERITY.get(llm_label, 0.05)
        cls_term = 0.40 * (new_sev * llm_conf - old_sev * nlp["threat_confidence"])
        nlp["threat_score"] = round(max(0.0, min(100.0, nlp["threat_score"] + cls_term * 100)), 1)
        nlp["threat_label"] = llm_label
        nlp["threat_confidence"] = round(llm_conf, 4)
        if llm_sent in ("negative", "neutral", "positive"):
            nlp["sentiment_label"] = llm_sent
        record["overridden"] = True

    nlp["llm_verification"] = record

    # ── bind the 3-model sentiment consensus to Groq's independent sentiment ──
    consensus = nlp.get("sentiment_consensus")
    if isinstance(consensus, dict) and consensus and llm_sent in ("negative", "neutral", "positive"):
        consensus["groq_sentiment"] = llm_sent
        consensus["groq_agrees"] = (llm_sent == consensus.get("label"))


_TRANSLATE_SYSTEM = (
    "You translate social-media posts to English for police analysts. Posts "
    "are usually Hindi, Gujarati, or romanized Hinglish/Gujlish, but may be "
    "ANY language (e.g. Tagalog, Bengali, Marathi) — detect the language "
    "yourself and translate faithfully. Keep hashtags/handles/URLs as-is. "
    "Reply ONLY with JSON: "
    '{"translations": [{"id": <post id>, "en": "<English translation>"}, ...]} '
    "— one entry per post, same ids as given."
)

TRANSLATE_MAX_PER_TICK = 40

# Devanagari + Gujarati script ranges: posts mixing scripts are often
# language-detected as "English" but still need a gloss for the analyst.
_INDIC_RE = re.compile("[ऀ-ॿ઀-૿]")


def needs_translation(text: str, nlp: dict) -> bool:
    if nlp.get("translation"):
        return False
    lang = nlp.get("language")
    return bool((lang and lang != "English") or _INDIC_RE.search(text))


async def translate_enriched(texts: list[str], enriched: list[dict]) -> int:
    """Fill in an English translation for every post that needs one (non-English
    or containing Indic script) in a freshly enriched batch (mutates
    nlp["translation"]). Returns how many were done."""
    if not enabled():
        return 0
    candidates = [
        i for i, n in enumerate(enriched) if needs_translation(texts[i], n)
    ][:TRANSLATE_MAX_PER_TICK]
    if not candidates:
        return 0
    from app.services.groq_client import chat_json

    try:
        # translation is high-volume background work — the fast model does it
        # fine and keeps the big model's daily budget for analyst actions
        data, _ = await chat_json([
            {"role": "system", "content": _TRANSLATE_SYSTEM},
            {"role": "user", "content": json.dumps(
                {"posts": [{"id": i, "text": texts[i][:600]} for i in candidates]},
                ensure_ascii=False)},
        ], model=settings.GROQ_MODEL_FAST)
    except Exception as exc:
        log.warning("Groq translate errored (%s) — batch stays untranslated", exc)
        return 0
    if data is None:
        log.warning("Groq translate failed on every model — batch stays untranslated")
        return 0
    n = 0
    for r in data.get("translations", []):
        try:
            i, en = int(r.get("id")), str(r.get("en", "")).strip()
        except (TypeError, ValueError):
            continue
        if i in candidates and en:
            enriched[i]["translation"] = en
            n += 1
    if n:
        log.info("Groq translated %d non-English posts", n)
    return n


async def verify_enriched(texts: list[str], enriched: list[dict]) -> int:
    """Verify the risky subset of a freshly enriched batch, in place.
    Returns how many posts were LLM-verified."""
    if not enabled():
        return 0
    if settings.SIMULATION_ENABLED:
        # demo stream is high-volume — only the risky subset goes to the LLM
        candidates = [
            i for i, n in enumerate(enriched)
            if n["threat_score"] >= settings.GROQ_VERIFY_MIN_SCORE
            or (n["threat_label"] != "Neutral" and n["threat_confidence"] < 0.55)
        ]
    else:
        # live mode: every real post gets a second opinion, riskiest first
        candidates = sorted(range(len(enriched)),
                            key=lambda i: -enriched[i]["threat_score"])
    candidates = candidates[: settings.GROQ_MAX_PER_TICK]
    if not candidates:
        return 0
    try:
        results = await _call_groq([{"id": i, "text": texts[i]} for i in candidates])
    except Exception as exc:
        log.warning("Groq verify errored (%s) — batch stays unverified", exc)
        return 0
    if not results:
        return 0
    by_id = {}
    for r in results:
        try:
            by_id[int(r.get("id"))] = r
        except (TypeError, ValueError):
            continue
    n = 0
    for i in candidates:
        if i in by_id:
            _reconcile(enriched[i], by_id[i])
            n += 1
    if n:
        log.info("Groq verified %d/%d risky posts", n, len(candidates))
    return n


async def summarize_briefing(text: str) -> str:
    """Uses LLM to summarize recent threat data into a concise intelligence briefing."""
    if not enabled():
        return text
    from app.services.groq_client import chat

    try:
        content, _ = await chat([
            {"role": "system", "content": "You are a senior intelligence officer summarizing threat data into a concise 1-paragraph briefing for local law enforcement."},
            {"role": "user", "content": f"Summarize this data into a short tactical briefing:\n\n{text}"},
        ], temperature=0.3, json_mode=False)
        if content:
            return content.strip()
    except Exception as exc:
        log.warning("Groq briefing failed (%s)", exc)
    return text
