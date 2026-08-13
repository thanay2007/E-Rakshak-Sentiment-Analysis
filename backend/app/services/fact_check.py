"""News corroboration — the external half of a post's evidence.

The models judge tone from the text. That is a claim about the post, and it is
not enough on its own for an analyst: a furious post about a bridge collapse
reads very differently once you know three outlets are reporting the collapse.
This service supplies that outside context, and it is deliberately the only
place in the product that reaches for facts about the world.

Three independent indexes, queried in order and merged:

  1. **Google News RSS** — keyless, unmetered, no descriptions. The background
     ingest loop uses only this one, so collection never depends on a quota.
  2. **GNews (gnews.io)** — descriptions and publish timestamps. 100 req/day
     free, so analyst-triggered paths only (`deep=True`), behind a daily cap.
  3. **NewsAPI.org** — a second commercial index with a different publisher
     mix. That difference is the reason it exists here: two indexes surfacing
     the same story is corroboration, one index having it is a search result.
     Same free-tier ceiling, same cap.

Every article carries the `api` that produced it, so the evidence block in the
post drawer can attribute each headline to the service it came from rather than
presenting an undifferentiated list. Sources that returned nothing are still
named, because "NewsAPI found no coverage" is itself evidence and hiding it
would overstate what was checked.

The verdict informs, it never overrides a label.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

from app.config import settings

log = logging.getLogger("sentinel.factcheck")

RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
GNEWS_URL = "https://gnews.io/api/v4/search"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
MAX_CHECKS_PER_TICK = 10

GOOGLE_NEWS = "Google News RSS"
GNEWS = "GNews API"
NEWSAPI = "NewsAPI.org"

# Per-API daily budget tracking (in-memory; resets on date change / restart).
_budget_day: date | None = None
_used: dict[str, int] = {GNEWS: 0, NEWSAPI: 0}


def _roll_day() -> None:
    global _budget_day
    today = datetime.now(timezone.utc).date()
    if _budget_day != today:
        _budget_day = today
        for k in _used:
            _used[k] = 0


def _budget_left(api: str) -> bool:
    _roll_day()
    if api == GNEWS:
        return bool(settings.GNEWS_API_KEY) and _used[GNEWS] < settings.GNEWS_DAILY_BUDGET
    if api == NEWSAPI:
        return bool(settings.NEWSAPI_KEY) and _used[NEWSAPI] < settings.NEWSAPI_DAILY_BUDGET
    return False


def news_status() -> dict:
    """What the Settings page shows for the evidence sources."""
    _roll_day()
    return {
        "sources": [
            {"name": GOOGLE_NEWS, "configured": True, "keyless": True,
             "used_today": None, "daily_budget": None,
             "note": "Always available — used by the background collector."},
            {"name": GNEWS, "configured": bool(settings.GNEWS_API_KEY), "keyless": False,
             "used_today": _used[GNEWS], "daily_budget": settings.GNEWS_DAILY_BUDGET,
             "note": "Analyst-triggered checks and evidence dossiers."},
            {"name": NEWSAPI, "configured": bool(settings.NEWSAPI_KEY), "keyless": False,
             "used_today": _used[NEWSAPI], "daily_budget": settings.NEWSAPI_DAILY_BUDGET,
             "note": "Second independent index — corroborates GNews results."},
        ]
    }


async def _google_news(client: httpx.AsyncClient, query: str) -> list[dict]:
    r = await client.get(RSS.format(q=quote_plus(query)))
    r.raise_for_status()
    feed = feedparser.parse(r.text)
    return [{
        "title": e.get("title", ""),
        "source": (e.get("source") or {}).get("title", ""),
        "link": e.get("link", ""),
        "published": e.get("published", ""),
        "description": "",
        "api": GOOGLE_NEWS,
    } for e in feed.entries[:6]]


async def _gnews(client: httpx.AsyncClient, query: str) -> list[dict]:
    _used[GNEWS] += 1
    r = await client.get(GNEWS_URL, params={
        "q": query, "apikey": settings.GNEWS_API_KEY,
        "lang": "en", "country": "in", "max": 10, "sortby": "relevance",
    })
    if r.status_code != 200:
        log.warning("GNews search failed: HTTP %s %s", r.status_code, r.text[:150])
        return []
    return [{
        "title": a.get("title", ""),
        "source": (a.get("source") or {}).get("name", ""),
        "link": a.get("url", ""),
        "published": a.get("publishedAt", ""),
        "description": (a.get("description") or "")[:220],
        "api": GNEWS,
    } for a in r.json().get("articles", [])]


async def _newsapi(client: httpx.AsyncClient, query: str) -> list[dict]:
    """NewsAPI.org /v2/everything.

    Scoped to the last 30 days because the free tier will not serve older
    articles and returns an error rather than an empty list if asked. The key
    goes in the X-Api-Key header, not the query string, so it does not end up
    in proxy logs or in the httpx error text on a non-200.
    """
    _used[NEWSAPI] += 1
    since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    r = await client.get(NEWSAPI_URL,
                         params={"q": query, "language": "en", "sortBy": "relevancy",
                                 "pageSize": 10, "from": since},
                         headers={"X-Api-Key": settings.NEWSAPI_KEY})
    if r.status_code != 200:
        log.warning("NewsAPI search failed: HTTP %s %s", r.status_code, r.text[:150])
        return []
    return [{
        "title": a.get("title", "") or "",
        "source": (a.get("source") or {}).get("name", ""),
        "link": a.get("url", ""),
        "published": a.get("publishedAt", ""),
        "description": (a.get("description") or "")[:220],
        "api": NEWSAPI,
    } for a in r.json().get("articles", [])]


def _query_for(nlp: dict, text: str) -> str:
    terms = [k for k in (nlp.get("keywords") or []) if len(k) > 2][:4]
    if not terms:  # fall back to the first few words of the post itself
        terms = [w for w in text.split() if len(w) > 3][:5]
    return " ".join(terms)


def _needs_check(nlp: dict) -> bool:
    """Which posts get a background corroboration lookup.

    Negative posts that are travelling are the ones where outside context
    changes an analyst's reading, and rumor-intent posts are the ones where the
    absence of coverage is itself informative. Everything else would spend a
    request to learn nothing.
    """
    if nlp.get("intent") == "rumor":
        return True
    return (nlp.get("sentiment_label") == "negative"
            and nlp.get("concern_score", 0) >= settings.ALERT_THRESHOLD)


async def check_claim(client: httpx.AsyncClient, query: str, deep: bool = False) -> dict:
    """One corroboration lookup → a fact_check record.

    deep=True (analyst-triggered paths only) additionally queries GNews and
    NewsAPI and merges their articles in — richer metadata and a second
    independent index, at one unit each from the 100/day free tiers.
    """
    by_api: dict[str, list[dict]] = {}
    sources: list[str] = []
    attempted: list[str] = []

    try:
        by_api[GOOGLE_NEWS] = await _google_news(client, query)
    except Exception as exc:
        log.warning("Google News lookup failed (%s)", exc)
        by_api[GOOGLE_NEWS] = []
    attempted.append(GOOGLE_NEWS)

    if deep:
        for api, fetch in ((GNEWS, _gnews), (NEWSAPI, _newsapi)):
            if not _budget_left(api):
                continue
            attempted.append(api)
            try:
                by_api[api] = await fetch(client, query)
            except Exception as exc:
                log.warning("%s lookup errored (%s)", api, exc)
                by_api[api] = []

    # Round-robin the merge rather than concatenating. Appending each index in
    # turn and then truncating meant whichever API was queried first filled the
    # whole list and the others were invisible — which defeats the only reason
    # to run a second index. Interleaving guarantees every API that answered is
    # represented in what the analyst actually sees.
    matches: list[dict] = []
    seen: set[str] = set()
    order = [a for a in attempted if by_api.get(a)]
    for rank in range(max((len(v) for v in by_api.values()), default=0)):
        for api in order:
            bucket = by_api[api]
            if rank >= len(bucket):
                continue
            a = bucket[rank]
            key = a["title"].strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            matches.append(a)
            if api not in sources:
                sources.append(api)

    n = len(matches)
    # Independent APIs agreeing is stronger than one index returning a lot.
    n_apis = len(sources)
    if n >= 2 and n_apis >= 2:
        verdict = "corroborated"
        note = (f"{n} reports across {n_apis} independent news indexes match these "
                "terms — the underlying event appears real (the post may still "
                "frame it misleadingly).")
    elif n >= 2:
        verdict = "corroborated"
        note = (f"{n} news reports match these terms — the underlying event appears "
                "real (the post may still frame it misleadingly).")
    elif n == 1:
        verdict = "partially corroborated"
        note = "Only one news report found — treat as unconfirmed."
    else:
        verdict = "uncorroborated"
        note = ("No independent news coverage found for these terms — consistent "
                "with an unverified or purely local claim.")
    return {
        "checked": True, "query": query, "verdict": verdict, "note": note,
        "sources": sources, "attempted": attempted, "matches": matches[:8],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def _check_one(client: httpx.AsyncClient, nlp: dict, text: str) -> None:
    query = _query_for(nlp, text)
    if not query:
        return
    nlp["fact_check"] = await check_claim(client, query)


async def corroborate_enriched(texts: list[str], enriched: list[dict]) -> int:
    """Corroborate the subset of a freshly enriched batch where outside context
    changes the reading, in place (adds nlp["fact_check"]). Returns how many
    posts were checked."""
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
                log.warning("corroboration failed for post %d: %s", i, exc)
    if n_done:
        log.info("Corroborated %d high-concern posts against news sources", n_done)
    return n_done
