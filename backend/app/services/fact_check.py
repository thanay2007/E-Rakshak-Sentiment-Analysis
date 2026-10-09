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
import re
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


_STOP = set("""
a about above after again against all also am an and any are as at be because been
before being below between both but by can could did do does doing down during each
even ever every few for from further had has have having he her here hers him his how
i if in into is it its itself just like make many may me more most much must my never
no nor not now of off often on once one only or other our out over own same she should
so some such than that the their them then there these they this those through to too
under until up upon us very was we were what when where which while who whom why will
with would you your yours always time times fully full can't cannot dont don't
""".split())

#: Hashtags that name a channel, a year or a mood rather than the subject —
#: `#indialivenews2024`, `#viral`, `#breaking`. Searching on them finds the
#: channel's other stories, which is how unrelated headlines got in.
_GENERIC_TAG = re.compile(
    r"(news|live|viral|trend|breaking|update|latest|today|video|reels?|shorts|"
    r"explore|fyp|foryou|follow|like|share|subscribe|\d{4})", re.I)

_HASHTAG = re.compile(r"#(\w{3,})", re.UNICODE)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]+")


def _split_tag(tag: str) -> str:
    """`NanaPatekar` → `Nana Patekar`. An all-lowercase tag cannot be split
    reliably and is kept whole; `_relevant` matches it with spaces removed."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", tag)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _entities(text: str) -> list[str]:
    """What the post is specifically about: subject hashtags, then names.

    A name is a run of capitalised words that does not start a sentence —
    "Harish Rana", "Surat Police". Sentence-initial words are skipped because
    every sentence starts with a capital, and "Losing" is not a name.
    """
    out: list[str] = []
    for tag in _HASHTAG.findall(text or ""):
        if not _GENERIC_TAG.search(tag) and not tag.isdigit():
            out.append(_split_tag(tag))
    body = _HASHTAG.sub(" ", text or "")
    for sentence in re.split(r"(?<=[.!?।])\s+|\n+", body):
        words = sentence.split()
        run: list[str] = []
        for i, raw in enumerate(words + [""]):
            w = raw.strip(".,;:!?\"'()[]—–-“”‘’")
            if i > 0 and w[:1].isupper() and w.lower() not in _STOP and _WORD.fullmatch(w):
                run.append(w)
                continue
            if run:
                out.append(" ".join(run))
                run = []
    seen, uniq = set(), []
    for e in out:
        k = _norm(e)
        if len(k) >= 3 and k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def _content_words(text: str) -> list[str]:
    body = _HASHTAG.sub(" ", text or "")
    words = [w.lower().strip("'’") for w in _WORD.findall(body)]
    out: list[str] = []
    for w in words:
        if len(w) > 3 and w not in _STOP and w not in out:
            out.append(w)
    return out


def _query_for(nlp: dict, text: str) -> str:
    """Search terms for a post, most specific first.

    Entities (subject hashtags, names) when the post has any — those are what
    a news report about the same event would also contain. Otherwise the
    post's content words, never its first five words verbatim: that used to
    send "Losing father deep trauma son—an" to the news indexes, and every
    result was about something else.
    """
    ents = _entities(text)
    if ents:
        return " ".join(ents[:3])
    terms = [k for k in (nlp.get("keywords") or []) if len(k) > 2][:2]
    for w in _content_words(text):
        if len(terms) >= 4:
            break
        if w not in terms:
            terms.append(w)
    return " ".join(terms)


def _stem(w: str) -> str:
    return w[:5] if len(w) > 5 else w


def _relevant(article: dict, query: str, entities: list[str]) -> bool:
    """Is this article about the post, or did the index just return something?

    The commercial indexes answer every query — NewsAPI will hand back an anime
    listing for "losing father deep trauma" — so a hit is not evidence until
    the headline/description actually shares the subject. When the post names
    something (`entities`), at least one name must appear, compared with spaces
    removed so the hashtag `nanapatekar` finds "Nana Patekar". Otherwise most
    of the query's words must — three of them, or all if there are fewer.
    """
    blob = f"{article.get('title', '')} {article.get('description', '')}"
    if entities:
        flat = _norm(blob)
        return any(_norm(e) in flat for e in entities)
    stems = {_stem(w.lower()) for w in _WORD.findall(blob)}
    words = [_norm(w) for w in query.lower().split() if w not in _STOP and _norm(w)]
    if not words:
        return False
    hits = sum(_stem(w) in stems for w in words)
    return hits >= min(3, len(words))


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


def _verdict(n: int, n_apis: int, returned: int) -> tuple[str, str]:
    """Verdict and analyst note for `n` relevant articles from `n_apis` indexes,
    out of `returned` articles the indexes handed back in total."""
    # Independent APIs agreeing is stronger than one index returning a lot.
    if n >= 2 and n_apis >= 2:
        return "corroborated", (
            f"{n} reports across {n_apis} independent news indexes cover this post's "
            "subject — the underlying event appears real (the post may still frame "
            "it misleadingly).")
    if n >= 2:
        return "corroborated", (
            f"{n} news reports cover this post's subject — the underlying event "
            "appears real (the post may still frame it misleadingly).")
    if n == 1:
        return "partially corroborated", "Only one related news report found — treat as unconfirmed."
    if returned:
        return "uncorroborated", (
            f"No related news found. The indexes returned {returned} article(s) for "
            "these terms, but none is about this post's subject.")
    return "uncorroborated", ("No related news found — consistent with an "
                              "unverified or purely local claim.")


def revalidate(record: dict | None, text: str) -> dict:
    """Re-apply the relevance rules to a stored fact_check record.

    Records saved before `_relevant` existed carry whatever the indexes
    returned — an anime listing filed as evidence for a post about a death.
    Running every stored record through the same filter on the way out fixes
    all of them at once, with no network calls, and is a no-op on records the
    current code produced.
    """
    if not record or not record.get("checked"):
        return record or {}
    entities = _entities(text or "")
    old = record.get("matches") or []
    kept = [m for m in old if _relevant(m, record.get("query", ""), entities)]
    if len(kept) == len(old):
        return record
    returned = len(old) + int(record.get("unrelated_dropped") or 0)
    sources = []
    for m in kept:
        if m.get("api") and m["api"] not in sources:
            sources.append(m["api"])
    verdict, note = _verdict(len(kept), len(sources), returned)
    return {**record, "matches": kept, "sources": sources, "verdict": verdict,
            "note": note, "unrelated_dropped": returned - len(kept)}


async def check_claim(client: httpx.AsyncClient, query: str, deep: bool = False,
                      text: str = "") -> dict:
    """One corroboration lookup → a fact_check record.

    deep=True (analyst-triggered paths only) additionally queries GNews and
    NewsAPI and merges their articles in — richer metadata and a second
    independent index, at one unit each from the 100/day free tiers.

    Only articles that pass `_relevant` count: an index returning ten
    unrelated stories is not ten reports of the event. `text` is the post the
    query was built from; the names in it are what an article must mention.
    """
    entities = _entities(text) if text else []
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
    returned = sum(len(v) for v in by_api.values())
    for api in by_api:
        by_api[api] = [a for a in by_api[api] if _relevant(a, query, entities)]
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

    verdict, note = _verdict(len(matches), len(sources), returned)
    return {
        "checked": True, "query": query, "verdict": verdict, "note": note,
        "sources": sources, "attempted": attempted, "matches": matches[:8],
        "unrelated_dropped": returned - len(matches),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def _check_one(client: httpx.AsyncClient, nlp: dict, text: str) -> None:
    query = _query_for(nlp, text)
    if not query:
        return
    nlp["fact_check"] = await check_claim(client, query, text=text)


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
