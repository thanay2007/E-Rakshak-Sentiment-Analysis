"""X adapter via twikit (github.com/d60/twikit) — no API key, uses a real X
account session (use a burner, not a personal account). Unofficial: it drives
X's internal endpoints, so it can break when X changes them and the account
can be rate-limited or suspended — keep volumes low.

Auth, in order of preference:
  1. X_AUTH_TOKEN + X_CT0 — the `auth_token` and `ct0` cookies copied from a
     browser logged into x.com (DevTools > Application > Cookies). Required in
     practice: Cloudflare blocks twikit's password login from Python clients.
  2. backend/x_cookies.json — a previously saved twikit cookie jar.
  3. X_USERNAME / X_EMAIL / X_PASSWORD password login (kept as last resort).

NOTE: PyPI twikit 2.3.3 is broken ("Couldn't get KEY_BYTE indices") since X's
March-2026 frontend change; install the patched build instead:
  pip install "git+https://github.com/d60/twikit.git@refs/pull/432/head"

Runs instead of the official XCollector when no X_BEARER_TOKEN is set; if
both are configured the ingestion pipeline's content-hash dedupe absorbs
the overlap.
"""
import logging
from datetime import datetime, timezone

from app.config import BASE_DIR, settings
from app.crawlers.base import Collector
from app.ml.geo import city_search_terms
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

COOKIES_FILE = BASE_DIR / "x_cookies.json"
QUERY_BUDGET = 450  # X search queries are capped around 512 chars


def _quote(t: str) -> str:
    return f'"{t}"' if " " in t else t


def _or_group(terms: list[str], budget: int) -> str:
    group = ""
    for t in terms:
        candidate = f"{group} OR {_quote(t)}" if group else _quote(t)
        if len(candidate) > budget:
            break
        group = candidate
    return group


def _has_indic(text: str) -> bool:
    return any(0x0900 <= ord(c) <= 0x0AFF for c in text)  # Devanagari + Gujarati


def _build_queries(watch_terms: list[str]) -> list[str]:
    """Focused queries instead of one global OR-soup. A bare OR of watchlist
    terms pulls worldwide noise (any 'boycott' tweet on the planet); every
    query here is anchored to the deployment's cities:

      1. city stream — any post naming a target city, in any script
      2. Indic-script watch terms — inherently local, no anchor needed
      3. Latin-script watch terms AND a city mention (X space = AND)

    Bare 'surat' is skipped — it means 'letter' in Indonesian/Malay and buries
    the stream in noise; the Devanagari/Gujarati spellings cover Surat."""
    cities, seen = [], set()
    for t in city_search_terms():
        t = t.strip()
        if t and t.lower() not in seen and t.lower() != "surat":
            seen.add(t.lower())
            cities.append(t)
    city_group = _or_group(cities, QUERY_BUDGET)

    indic, latin = [], []
    for t in watch_terms:
        t = t.strip()
        if not t or t.lower() in seen:
            continue
        seen.add(t.lower())
        (indic if _has_indic(t) else latin).append(t)

    queries = [f"({city_group}) -filter:retweets"]
    if indic:
        queries.append(f"({_or_group(indic, QUERY_BUDGET)}) -filter:retweets")
    if latin:
        latin_group = _or_group(latin, QUERY_BUDGET - len(city_group) - 20)
        queries.append(f"({latin_group}) ({city_group}) -filter:retweets")
    return queries


def _media_urls(tweet) -> list[str]:
    urls = []
    for m in getattr(tweet, "media", None) or []:
        u = (getattr(m, "media_url", None)
             or (m.get("media_url_https") if isinstance(m, dict) else None))
        if u:
            urls.append(u)
    return urls


def _parse_created(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:  # X internal format: 'Wed Oct 10 20:19:24 +0000 2018'
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


class TwikitXCollector(Collector):
    name = "X (twikit)"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._client = None  # twikit.Client, created lazily on first collect
        self._seen: set[str] = set()

    def is_configured(self) -> bool:
        return bool((settings.X_AUTH_TOKEN and settings.X_CT0)
                    or COOKIES_FILE.exists()
                    or (settings.X_USERNAME and settings.X_PASSWORD))

    async def _login(self):
        if self._client is not None:
            return self._client
        from twikit import Client  # imported lazily: optional dependency

        client = Client("en-US")
        if settings.X_AUTH_TOKEN and settings.X_CT0:
            client.set_cookies({"auth_token": settings.X_AUTH_TOKEN,
                                "ct0": settings.X_CT0})
        elif COOKIES_FILE.exists():
            client.load_cookies(str(COOKIES_FILE))
        else:
            # Password login — usually Cloudflare-blocked; cookies preferred.
            await client.login(
                auth_info_1=settings.X_USERNAME,
                auth_info_2=settings.X_EMAIL or settings.X_USERNAME,
                password=settings.X_PASSWORD,
                cookies_file=str(COOKIES_FILE),
            )
        self._client = client
        return client

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        from app.ml.geo import infer_city

        tweets = []
        try:
            client = await self._login()
            for query in _build_queries(watch_terms):
                tweets.extend(await client.search_tweet(query, "Latest", count=20))
        except Exception as exc:
            self._client = None  # force fresh login next tick after any failure
            log.warning("twikit X collect failed: %s", exc)
            if not tweets:
                return []

        posts: list[RawPost] = []
        dropped = 0
        for t in tweets:
            tid = str(getattr(t, "id", "") or "")
            text = (getattr(t, "text", "") or "").strip()
            if not tid or tid in self._seen or not text:
                continue
            self._seen.add(tid)
            # relevance gate: keep only posts that name a target city or are
            # written in a local script — X fuzzy-matches ("bo-boycott" hits a
            # "boycott" query) and would otherwise leak worldwide chatter in
            if infer_city(text) is None and not _has_indic(text):
                dropped += 1
                continue
            u = getattr(t, "user", None)
            handle = getattr(u, "screen_name", "") or "unknown"
            acct_created = _parse_created(getattr(u, "created_at", None))
            age = (datetime.utcnow() - acct_created).days if acct_created else 365
            posts.append(RawPost(
                platform="X",
                author_handle=handle,
                author_name=getattr(u, "name", "") or "",
                author_followers=getattr(u, "followers_count", 0) or 0,
                author_verified=bool(getattr(u, "is_blue_verified", False)
                                     or getattr(u, "verified", False)),
                author_account_age_days=age,
                text=text,
                hashtags=list(getattr(t, "hashtags", None) or
                              [w.lstrip("#") for w in text.split() if w.startswith("#")]),
                engagement={"likes": getattr(t, "favorite_count", 0) or 0,
                            "shares": getattr(t, "retweet_count", 0) or 0,
                            "comments": getattr(t, "reply_count", 0) or 0,
                            "views": int(getattr(t, "view_count", 0) or 0)},
                url=f"https://x.com/{handle}/status/{tid}",
                media_urls=_media_urls(t),
                created_at=_parse_created(getattr(t, "created_at", None)),
            ))
        if dropped:
            log.info("twikit X: dropped %d off-scope tweets (no target city, no local script)", dropped)
        return posts
