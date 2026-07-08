"""Reddit adapter — official OAuth2 API (oauth.reddit.com).

Authenticates with the client-credentials grant of a Reddit "script" app
(REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET) and combines both collection
strategies:
  1. Seed subreddits (REDDIT_SUBREDDITS) — /r/<sub>/new for each target-city
     sub, geo-tagged via the optional :City suffix.
  2. Watchlist search — /search over the analyst keywords/hashtags.
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


class RedditCollector(Collector):
    name = "Reddit"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._token: str = ""
        self._token_expires: float = 0.0

    def is_configured(self) -> bool:
        return bool(settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET)

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

    def _listing_to_posts(self, data: dict, city: str) -> list[RawPost]:
        posts: list[RawPost] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            pid = d.get("id")
            if not pid or pid in self._seen:
                continue
            self._seen.add(pid)
            text = f"{d.get('title', '')} {d.get('selftext', '')[:400]}".strip()
            if not text:
                continue
            posts.append(RawPost(
                platform="Reddit",
                author_handle=d.get("author", "unknown"), author_name=d.get("author", ""),
                text=text,
                location=city,
                hashtags=[d.get("subreddit", "")] if d.get("subreddit") else [],
                engagement={"likes": d.get("ups", 0), "shares": 0,
                            "comments": d.get("num_comments", 0), "views": 0},
                url="https://reddit.com" + d.get("permalink", ""),
                created_at=datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc).replace(tzinfo=None)
                if d.get("created_utc") else None,
            ))
        return posts

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
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
