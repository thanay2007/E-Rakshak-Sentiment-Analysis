"""Reddit adapter — official OAuth2 API (oauth.reddit.com) with a keyless
fallback to PullPush (api.pullpush.io), the community Pushshift successor.

With REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET set it authenticates via the
client-credentials grant of a Reddit "script" app (100 req/min quota).
Without credentials it queries PullPush's free submission-search API instead —
no key needed. (Reddit's own public .json listings are NOT used: since ~2024
Reddit 403-blocks non-browser HTTP clients regardless of User-Agent.)
PullPush indexes with some minutes-to-hours of lag, fine for trend monitoring.

Both modes combine the two collection strategies:
  1. Seed subreddits (REDDIT_SUBREDDITS) — newest posts of each target-city
     sub, geo-tagged via the optional :City suffix.
  2. Watchlist search — keyword search over the analyst watchlist.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.crawlers.base import Collector
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
PULLPUSH = "https://api.pullpush.io/reddit/search/submission/"


class RedditCollector(Collector):
    name = "Reddit"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._token: str = ""
        self._token_expires: float = 0.0

    def is_configured(self) -> bool:
        # Always on: OAuth when a script app is configured, public JSON otherwise.
        return True

    async def _auth(self, client: httpx.AsyncClient) -> str:
        if self._token and time.monotonic() < self._token_expires - 60:
            return self._token
        r = await client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET),
            headers={"User-Agent": settings.REDDIT_USER_AGENT},
        )
        r.raise_for_status()
        tok = r.json()
        self._token = tok["access_token"]
        self._token_expires = time.monotonic() + tok.get("expires_in", 3600)
        return self._token

    def _to_post(self, d: dict, city: str) -> RawPost | None:
        """One submission dict -> RawPost. Reddit listings and PullPush use the
        same field names; only the list wrapper differs."""
        pid = d.get("id")
        if not pid or pid in self._seen:
            return None
        self._seen.add(pid)
        body = d.get("selftext") or ""
        if body in ("[removed]", "[deleted]"):
            body = ""
        text = f"{d.get('title', '')} {body[:400]}".strip()
        if not text:
            return None
        created = d.get("created_utc") or 0
        link = d.get("url") or d.get("url_overridden_by_dest") or ""
        link_low = link.lower().split("?")[0]
        is_media = (link_low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif",
                                       ".mp4", ".webm"))
                    or "v.redd.it" in link_low)
        return RawPost(
            platform="Reddit",
            author_handle=d.get("author", "unknown"), author_name=d.get("author", ""),
            text=text,
            location=city,
            hashtags=[d.get("subreddit", "")] if d.get("subreddit") else [],
            engagement={"likes": d.get("ups") or d.get("score") or 0, "shares": 0,
                        "comments": d.get("num_comments", 0) or 0, "views": 0},
            url="https://reddit.com" + d.get("permalink", ""),
            media_urls=[link] if is_media else [],
            created_at=datetime.fromtimestamp(created, tz=timezone.utc).replace(tzinfo=None)
            if created else None,
        )

    def _listing_to_posts(self, data: dict, city: str) -> list[RawPost]:
        children = data.get("data", {}).get("children", [])
        return [p for c in children if (p := self._to_post(c.get("data", {}), city))]

    def _pullpush_to_posts(self, data: dict, city: str) -> list[RawPost]:
        return [p for d in data.get("data", []) if (p := self._to_post(d, city))]

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        if settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET:
            return await self._collect_oauth(watch_terms)
        return await self._collect_pullpush(watch_terms)

    async def _collect_oauth(self, watch_terms: list[str]) -> list[RawPost]:
        posts: list[RawPost] = []
        headers = {"User-Agent": settings.REDDIT_USER_AGENT}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                token = await self._auth(client)
                headers["Authorization"] = f"Bearer {token}"

                # 1. seed city subreddits
                for sub, city in settings.REDDIT_SUBREDDITS:
                    try:
                        r = await client.get(f"{API}/r/{sub}/new",
                                             params={"limit": 20}, headers=headers)
                        r.raise_for_status()
                        posts.extend(self._listing_to_posts(r.json(), city))
                    except Exception as exc:
                        log.warning("Reddit collect failed for r/%s: %s", sub, exc)
                    await asyncio.sleep(1)  # gap between queries inside one batch

                # 2. watchlist keyword search
                if watch_terms:
                    q = " OR ".join(watch_terms[:8])
                    r = await client.get(f"{API}/search",
                                         params={"q": q, "sort": "new", "limit": 20},
                                         headers=headers)
                    r.raise_for_status()
                    posts.extend(self._listing_to_posts(r.json(), city=""))
        except Exception as exc:
            log.warning("Reddit collect failed: %s", exc)
        return posts

    async def _collect_pullpush(self, watch_terms: list[str]) -> list[RawPost]:
        posts: list[RawPost] = []
        headers = {"User-Agent": settings.REDDIT_USER_AGENT}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # 1. seed city subreddits — newest indexed submissions
                for sub, city in settings.REDDIT_SUBREDDITS:
                    try:
                        r = await client.get(PULLPUSH,
                                             params={"subreddit": sub, "size": 20,
                                                     "sort": "desc"},
                                             headers=headers)
                        r.raise_for_status()
                        posts.extend(self._pullpush_to_posts(r.json(), city))
                    except Exception as exc:
                        log.warning("PullPush collect failed for r/%s: %s", sub, exc)
                    await asyncio.sleep(2)  # PullPush is a free community service — be gentle

                # 2. watchlist keyword search
                if watch_terms:
                    r = await client.get(PULLPUSH,
                                         params={"q": "|".join(watch_terms[:8]),
                                                 "size": 20, "sort": "desc"},
                                         headers=headers)
                    r.raise_for_status()
                    posts.extend(self._pullpush_to_posts(r.json(), city=""))
        except Exception as exc:
            log.warning("PullPush collect failed: %s", exc)
        return posts
