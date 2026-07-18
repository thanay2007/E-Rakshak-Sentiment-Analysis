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

import httpx

from app.config import THREAT_LABELS, settings
from app.ml.threat_score import SEVERITY

log = logging.getLogger("sentinel.groq")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM = (
    "You are a threat-intelligence reviewer for Gujarat police analysts. "
    "You will receive social-media posts (English, Hindi, Gujarati, or romanized "
    "Hinglish/Gujlish). For EACH post, independently assess:\n"
    f"- threat_label: exactly one of {THREAT_LABELS}\n"
    "- sentiment: negative | neutral | positive\n"
    "- confidence: 0.0-1.0 (your certainty in threat_label)\n"
    "- reason: one short sentence of evidence\n"
    'Reply ONLY with JSON: {"results": [{"id": <post id>, "threat_label": ..., '
    '"sentiment": ..., "confidence": ..., "reason": ...}, ...]} — one entry per post, '
    "same ids as given. Judge the text itself; do not assume unstated context."
)


def enabled() -> bool:
    return bool(settings.GROQ_API_KEY)


async def _call_groq(posts: list[dict]) -> list[dict] | None:
    """One batched request. posts: [{"id", "text"}]. Returns parsed results or None."""
    body = {
        "model": settings.GROQ_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(
                {"posts": [{"id": p["id"], "text": p["text"][:600]} for p in posts]},
                ensure_ascii=False)},
        ],
    }
    async with httpx.AsyncClient(timeout=settings.GROQ_TIMEOUT_SECONDS) as client:
        resp = await client.post(GROQ_URL, json=body, headers={
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        })
    if resp.status_code != 200:
        log.warning("Groq verify failed: HTTP %s %s", resp.status_code, resp.text[:200])
        return None
    content = resp.json()["choices"][0]["message"]["content"]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:          # salvage a JSON object out of prose
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
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
    record = {
        "model": settings.GROQ_MODEL,
        "llm_threat_label": llm_label,
        "llm_sentiment": llm_sent,
        "llm_confidence": round(llm_conf, 3),
        "reason": str(verdict.get("reason", ""))[:240],
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


async def verify_enriched(texts: list[str], enriched: list[dict]) -> int:
    """Verify the risky subset of a freshly enriched batch, in place.
    Returns how many posts were LLM-verified."""
    if not enabled():
        return 0
    candidates = [
        i for i, n in enumerate(enriched)
        if n["threat_score"] >= settings.GROQ_VERIFY_MIN_SCORE
        or (n["threat_label"] != "Neutral" and n["threat_confidence"] < 0.55)
    ][: settings.GROQ_MAX_PER_TICK]
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
    body = {
        "model": settings.GROQ_MODEL,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": "You are a senior intelligence officer summarizing threat data into a concise 1-paragraph briefing for local law enforcement."},
            {"role": "user", "content": f"Summarize this data into a short tactical briefing:\n\n{text}"},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=settings.GROQ_TIMEOUT_SECONDS) as client:
            resp = await client.post(GROQ_URL, json=body, headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            })
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning("Groq briefing failed (%s)", exc)
    return text
