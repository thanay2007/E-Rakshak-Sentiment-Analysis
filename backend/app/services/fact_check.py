"""Cross-source corroboration for suspected fake news.

When the pipeline (or the Groq second opinion) labels a post "Fake News" or
rumor-intent, check whether independent news outlets are reporting the same
story: one Google News RSS query built from the post's evidence keywords.
  - matching articles found  -> the underlying event is being reported by the
    press ("corroborated") — the claim may still be spun, but it isn't invented
  - nothing found            -> no independent reporting ("uncorroborated"),
    consistent with a fabricated/unverified claim
The verdict is stored on the post (`fact_check`) and shown to analysts next to
the LLM verification block — it informs, it never overrides.

Keyless (Google News RSS is public). Capped per tick to stay polite.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

log = logging.getLogger("sentinel.factcheck")

RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
MAX_CHECKS_PER_TICK = 10


def _query_for(nlp: dict, text: str) -> str:
    terms = [k for k in (nlp.get("keywords") or []) if len(k) > 2][:4]
    if not terms:  # fall back to the first few words of the post itself
        terms = [w for w in text.split() if len(w) > 3][:5]
    return " ".join(terms)


def _needs_check(nlp: dict) -> bool:
    llm = nlp.get("llm_verification") or {}
    if llm.get("llm_threat_label") == "Fake News":
        return True
    # Groq reviewed it and does NOT think it's fake news — trust that, don't
    # burn a check on a local-model false positive.
    if llm.get("llm_threat_label"):
        return nlp.get("intent") == "rumor"
    return nlp.get("threat_label") == "Fake News" or nlp.get("intent") == "rumor"


async def check_claim(client: httpx.AsyncClient, query: str) -> dict:
    """One Google News corroboration lookup -> a fact_check record."""
    r = await client.get(RSS.format(q=quote_plus(query)))
    r.raise_for_status()
    feed = feedparser.parse(r.text)
    matches = [{
        "title": e.get("title", ""),
        "source": (e.get("source") or {}).get("title", ""),
        "link": e.get("link", ""),
    } for e in feed.entries[:3]]
    n = len(feed.entries)
    if n >= 2:
        verdict = "corroborated"
        note = (f"{n} independent news reports match these terms — the underlying "
                "event appears real (the post may still frame it misleadingly).")
    elif n == 1:
        verdict = "partially corroborated"
        note = "Only one news report found — treat as unconfirmed."
    else:
        verdict = "uncorroborated"
        note = ("No independent news coverage found for these terms — consistent "
                "with a fabricated or unverified claim.")
    return {
        "checked": True, "query": query, "verdict": verdict, "note": note,
        "matches": matches,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def _check_one(client: httpx.AsyncClient, nlp: dict, text: str) -> None:
    query = _query_for(nlp, text)
    if not query:
        return
    nlp["fact_check"] = await check_claim(client, query)


async def corroborate_enriched(texts: list[str], enriched: list[dict]) -> int:
    """Fact-check the suspected-fake subset of a freshly enriched batch, in
    place (adds nlp["fact_check"]). Returns how many posts were checked."""
    candidates = [i for i, n in enumerate(enriched) if _needs_check(n)][:MAX_CHECKS_PER_TICK]
    if not candidates:
        return 0
    n_done = 0
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for i in candidates:
            try:
                await _check_one(client, enriched[i], texts[i])
                n_done += 1
            except Exception as exc:
                log.warning("fact-check failed for post %d: %s", i, exc)
    if n_done:
        log.info("Fact-checked %d suspected fake-news posts", n_done)
    return n_done
