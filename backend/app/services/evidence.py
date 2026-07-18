"""Analyst-grade evidence dossier for a single post.

Police analysts need more than a label: every judgement must trace back to
verbatim quotes, named techniques, and checkable sources. This service builds
that dossier on demand (drawer button -> POST /api/feed/{id}/evidence-report):

  1. Gather everything already known about the post: raw text + translation,
     the local model's full output, the Groq second opinion, author metadata,
     and the Google News corroboration (fetched now if not already stored).
  2. One Groq call assembles the structured dossier — claims extracted and
     individually assessed, verbatim evidence phrases with significance,
     corroboration citing ONLY the real news articles provided, account and
     risk assessment, recommended action, and explicit limitations.
  3. The dossier is stored on the post (evidence_report) so it becomes part
     of the record and appears in future exports.

The prompt forbids invented facts and invented sources: corroboration may cite
only the Google News articles passed in, and quotes must be verbatim.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import httpx

from app.config import THREAT_LABELS, settings
from app.database import session_scope
from app.models import Post
from app.services.fact_check import _query_for, check_claim

log = logging.getLogger("sentinel.evidence")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM = (
    "You are a senior threat-intelligence analyst preparing an evidence dossier "
    "for Gujarat police. The dossier may be attached to official reports, so it "
    "must be precise, verifiable and honest about uncertainty.\n\n"
    "You receive one social-media post with: original text, English translation, "
    "author/account metadata, engagement, the local ML model's classification, a "
    "prior LLM review, and real news-search results (the only external sources "
    "you may cite).\n\n"
    "Produce ONLY JSON with exactly these fields:\n"
    '- "summary": 2-3 sentences — what the post says and why it does or does not '
    "warrant the assigned label.\n"
    '- "claims": array (max 4) of {"claim": <the factual assertion, paraphrased>, '
    '"type": "factual claim"|"opinion"|"call to action"|"rumor", '
    '"assessment": "supported"|"contradicted"|"unverified", '
    '"basis": 1-2 sentences citing the news results or the absence of coverage}.\n'
    '- "evidence_phrases": array (max 4) of {"quote": <EXACT verbatim phrase from '
    'the original post>, "significance": why this phrase matters (technique used: '
    "e.g. unattributed statistic, communal framing, urgency cue, call to gather)}.\n"
    '- "corroboration": {"verdict": "corroborated"|"partially corroborated"|'
    '"uncorroborated"|"not applicable", "explanation": 2-3 sentences comparing the '
    "post's claims with the provided news articles, "
    '"citations": array of {"source", "title", "link"} — ONLY articles from the '
    "provided news results that are actually relevant; [] if none}.\n"
    '- "account_assessment": 1-2 sentences on the author signals (followers, account '
    "age, verification, amplification flag) and what they imply about reliability.\n"
    '- "risk_assessment": 2-3 sentences — realistic potential for offline harm, '
    "spread, or communal tension; be proportionate, do not exaggerate.\n"
    f'- "recommended_action": one of "no action"|"continue monitoring"|'
    '"verify with local unit"|"escalate to supervisor", plus one sentence of '
    "justification.\n"
    '- "limitations": 1-2 sentences on what this analysis cannot establish '
    "(e.g. author identity, image authenticity, ground truth).\n"
    '- "confidence": 0.0-1.0 overall.\n\n'
    "Rules: quotes must be verbatim from the post (original script). Never invent "
    "sources, events, or context. If the news results are empty or irrelevant, say "
    "so plainly. Judge the text itself."
)


def _post_payload(p: Post) -> dict:
    return {
        "platform": p.platform,
        "original_text": p.text[:1500],
        "english_translation": p.translation or "(post is in English)",
        "language": p.language,
        "hashtags": p.hashtags or [],
        "author": {
            "handle": p.author_handle, "display_name": p.author_name,
            "followers": p.author_followers, "verified": p.author_verified,
            "account_age_days": p.author_account_age_days,
            "amplification_flag": p.is_amplified,
        },
        "engagement": p.engagement or {},
        "posted_at": p.created_at.isoformat() if p.created_at else None,
        "local_model": {
            "threat_label": p.threat_label,
            "confidence": p.threat_confidence,
            "class_probabilities": p.class_probs or {},
            "sentiment": p.sentiment_label,
            "toxicity": p.toxicity_score,
            "intent": p.intent,
            "hate_flags": p.hate_flags or [],
            "evidence_keywords": p.keywords or [],
        },
        "prior_llm_review": p.llm_verification or {},
    }


async def generate_report(post_id: str) -> dict:
    if not settings.GROQ_API_KEY:
        return {"ok": False, "error": "GROQ_API_KEY not configured — the evidence "
                                      "dossier needs the LLM layer."}
    with session_scope() as s:
        post = s.get(Post, post_id)
        if not post:
            return {"ok": False, "error": "Post not found"}
        payload = _post_payload(post)
        fact = dict(post.fact_check or {})
        keywords = list(post.keywords or [])
        text_for_query = post.translation or post.text

    async with httpx.AsyncClient(timeout=settings.GROQ_TIMEOUT_SECONDS,
                                 follow_redirects=True) as client:
        # make sure we have real news results to cite (fetched now if missing)
        if not fact.get("checked"):
            query = _query_for({"keywords": keywords}, text_for_query)
            if query:
                try:
                    fact = await check_claim(client, query)
                except Exception as exc:
                    log.warning("evidence: news lookup failed (%s)", exc)
        payload["news_search_results"] = {
            "query": fact.get("query", ""),
            "articles": fact.get("matches", []),
            "note": "These are real Google News India results for the post's key "
                    "terms — the ONLY citable external sources.",
        }

        body = {
            "model": settings.GROQ_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        resp = await client.post(GROQ_URL, json=body, headers={
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        })
    if resp.status_code != 200:
        log.warning("evidence dossier failed: HTTP %s %s", resp.status_code, resp.text[:200])
        return {"ok": False, "error": "LLM analysis unavailable right now — try again."}
    content = resp.json()["choices"][0]["message"]["content"]
    try:
        dossier = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return {"ok": False, "error": "LLM returned an unparseable dossier — try again."}
        dossier = json.loads(m.group(0))

    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.GROQ_MODEL,
        **{k: dossier.get(k) for k in (
            "summary", "claims", "evidence_phrases", "corroboration",
            "account_assessment", "risk_assessment", "recommended_action",
            "limitations", "confidence")},
    }
    with session_scope() as s:
        post = s.get(Post, post_id)
        if post:
            post.evidence_report = record
            if fact.get("checked") and not (post.fact_check or {}).get("checked"):
                post.fact_check = fact  # keep the news lookup as part of the record
            s.add(post)
            s.commit()
    return {"ok": True, **record}
