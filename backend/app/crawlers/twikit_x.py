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


def _build_query(watch_terms: list[str]) -> str:
    """OR the watchlist with every script variant of the target cities
    (English/Hindi/Gujarati/romanized) so all five languages come back.
    Bare 'surat' is skipped — it means 'letter' in Indonesian/Malay and buries
    the stream in noise; the Devanagari/Gujarati spellings cover Surat."""
    terms, seen = [], set()
    for term in watch_terms + city_search_terms():
        t = term.strip()
        if not t or t.lower() in seen or t.lower() == "surat":
            continue
        seen.add(t.lower())
        terms.append(f'"{t}"' if " " in t else t)
    query = ""
    for t in terms:
        candidate = f"{query} OR {t}" if query else t
        if len(candidate) > QUERY_BUDGET:
            break
        query = candidate
    return f"({query}) -filter:retweets"


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
        query = _build_query(watch_terms)
        try:
            client = await self._login()
            tweets = await client.search_tweet(query, "Latest", count=25)
        except Exception as exc:
            self._client = None  # force fresh login next tick after any failure
            log.warning("twikit X collect failed: %s", exc)
            return []

        posts: list[RawPost] = []
        for t in tweets:
            tid = str(getattr(t, "id", "") or "")
            text = (getattr(t, "text", "") or "").strip()
            if not tid or tid in self._seen or not text:
                continue
            self._seen.add(tid)
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
        return posts
