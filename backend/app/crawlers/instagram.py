"""Instagram adapter — official Instagram Graph API.

Two collection strategies, both key-based (no scraping):
  1. Seed accounts (business discovery): recent media of public
     business/creator accounts listed in IG_SEED_USERNAMES — the top local
     pages per target city, optional :City geo-tag, e.g.
         IG_SEED_USERNAMES=narendramodi,suratsmartcity:Surat
  2. Watchlist hashtags (ig_hashtag_search → recent_media). Meta caps an app
     at 30 unique hashtags per 7 days, so only the first few watchlist
     hashtags are queried and hashtag ids are cached.

Requires IG_ACCESS_TOKEN plus IG_BUSINESS_ACCOUNT_ID (the Instagram
professional account linked to your Meta app — both discovery and hashtag
endpoints are namespaced under it).
"""
import asyncio
import logging
from datetime import datetime

import httpx

from app.config import settings
from app.crawlers.base import Collector
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

MEDIA_FIELDS = "id,caption,like_count,comments_count,permalink,timestamp,username"
# Hashtag endpoints must not request username — Meta blocks it there (privacy).
HASHTAG_MEDIA_FIELDS = "id,caption,like_count,comments_count,permalink,timestamp"
MAX_HASHTAGS_PER_CYCLE = 3


def _iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("+0000", "+00:00")).replace(tzinfo=None)


class InstagramCollector(Collector):
    name = "Instagram"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._hashtag_ids: dict[str, str] = {}

    def is_configured(self) -> bool:
        return bool(settings.IG_ACCESS_TOKEN and settings.IG_BUSINESS_ACCOUNT_ID)

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{settings.FB_API_VERSION}"

    def _media_to_post(self, m: dict, city: str, followers: int = 0) -> RawPost | None:
        mid = m.get("id", "")
        text = (m.get("caption") or "").strip()
        if not mid or mid in self._seen or not text:
            return None
        self._seen.add(mid)
        handle = m.get("username", "instagram")
        return RawPost(
            platform="Instagram",
            author_handle=handle, author_name=handle,
            author_followers=followers,
            text=text[:1000],
            location=city,
            engagement={"likes": m.get("like_count", 0), "shares": 0,
                        "comments": m.get("comments_count", 0), "views": 0},
            url=m.get("permalink", ""),
            created_at=_iso(m.get("timestamp")),
        )

    async def _seed_accounts(self, client: httpx.AsyncClient) -> list[RawPost]:
        posts: list[RawPost] = []
        for username, city in settings.IG_SEED_USERNAMES:
            try:
                r = await client.get(f"{self._base}/{settings.IG_BUSINESS_ACCOUNT_ID}", params={
                    "fields": f"business_discovery.username({username})"
                              f"{{username,name,followers_count,media.limit(20){{{MEDIA_FIELDS}}}}}",
                    "access_token": settings.IG_ACCESS_TOKEN,
                })
                r.raise_for_status()
                bd = r.json().get("business_discovery", {})
            except Exception as exc:
                log.warning("Instagram discovery failed for @%s: %s", username, exc)
                continue
            followers = bd.get("followers_count", 0)
            for m in bd.get("media", {}).get("data", []):
                m.setdefault("username", bd.get("username", username))
                post = self._media_to_post(m, city, followers)
                if post:
                    posts.append(post)
            await asyncio.sleep(1)  # gap between account queries inside one batch
        return posts

    async def _hashtags(self, client: httpx.AsyncClient, watch_terms: list[str]) -> list[RawPost]:
        posts: list[RawPost] = []
        tags = [t.lstrip("#") for t in watch_terms if t and t.replace("#", "").isalnum()]
        for tag in tags[:MAX_HASHTAGS_PER_CYCLE]:
            try:
                if tag not in self._hashtag_ids:
                    r = await client.get(f"{self._base}/ig_hashtag_search", params={
                        "user_id": settings.IG_BUSINESS_ACCOUNT_ID, "q": tag,
                        "access_token": settings.IG_ACCESS_TOKEN,
                    })
                    r.raise_for_status()
                    data = r.json().get("data", [])
                    if not data:
                        continue
                    self._hashtag_ids[tag] = data[0]["id"]
                r = await client.get(f"{self._base}/{self._hashtag_ids[tag]}/recent_media", params={
                    "user_id": settings.IG_BUSINESS_ACCOUNT_ID,
                    "fields": HASHTAG_MEDIA_FIELDS, "limit": 15,
                    "access_token": settings.IG_ACCESS_TOKEN,
                })
                r.raise_for_status()
                items = r.json().get("data", [])
            except Exception as exc:
                log.warning("Instagram hashtag collect failed for #%s: %s", tag, exc)
                continue
            for m in items:
                post = self._media_to_post(m, city="")
                if post:
                    post.hashtags = [tag]
                    posts.append(post)
            await asyncio.sleep(1)
        return posts

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        async with httpx.AsyncClient(timeout=20) as client:
            posts = await self._seed_accounts(client)
            posts.extend(await self._hashtags(client, watch_terms))
        return posts
