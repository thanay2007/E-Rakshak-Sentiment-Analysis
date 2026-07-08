"""YouTube adapter — Data API v3 search over watchlist terms.
Activates when YOUTUBE_API_KEY is set."""
import logging
from datetime import datetime

import httpx

from app.config import settings
from app.crawlers.base import Collector
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")
API = "https://www.googleapis.com/youtube/v3/search"


class YouTubeCollector(Collector):
    name = "YouTube"
    # YouTube search costs 100 quota units per call (10k/day) — keep it slow.
    min_interval_seconds = max(settings.CRAWL_MIN_INTERVAL_SECONDS, 900)

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_configured(self) -> bool:
        return bool(settings.YOUTUBE_API_KEY)

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        if not watch_terms:
            return []
        params = {
            "part": "snippet", "q": " | ".join(watch_terms[:10]), "type": "video",
            "order": "date", "maxResults": 15, "key": settings.YOUTUBE_API_KEY,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(API, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            log.warning("YouTube collect failed: %s", exc)
            return []

        posts: list[RawPost] = []
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if not vid or vid in self._seen:
                continue
            self._seen.add(vid)
            sn = item["snippet"]
            posts.append(RawPost(
                platform="YouTube",
                author_handle=sn.get("channelTitle", "channel"), author_name=sn.get("channelTitle", ""),
                text=f"{sn.get('title', '')} — {sn.get('description', '')}".strip(" —"),
                url=f"https://youtube.com/watch?v={vid}",
                created_at=datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")).replace(tzinfo=None)
                if sn.get("publishedAt") else None,
            ))
        return posts
