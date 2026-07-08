"""Generic web/RSS adapter — monitors any comma-separated RSS_FEEDS list."""
import logging
from datetime import datetime

from app.config import settings
from app.crawlers.base import Collector
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")


class RSSCollector(Collector):
    name = "Web/RSS"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_configured(self) -> bool:
        return bool(settings.RSS_FEEDS)

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        try:
            import feedparser
        except ImportError:
            return []
        posts: list[RawPost] = []
        for feed_url in settings.RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
            except Exception as exc:
                log.warning("RSS parse failed for %s: %s", feed_url, exc)
                continue
            for e in feed.entries[:15]:
                uid = e.get("id") or e.get("link", "")
                if not uid or uid in self._seen:
                    continue
                self._seen.add(uid)
                created = None
                if e.get("published_parsed"):
                    created = datetime(*e.published_parsed[:6])
                posts.append(RawPost(
                    platform="Web",
                    author_handle=feed.feed.get("title", "rss")[:40], author_name=feed.feed.get("title", ""),
                    text=f"{e.get('title', '')} {e.get('summary', '')[:400]}".strip(),
                    url=e.get("link", ""), created_at=created,
                ))
        return posts
