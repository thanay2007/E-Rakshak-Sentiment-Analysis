"""X (Twitter) adapter — v2 recent-search anchored to the target cities.
Activates automatically when X_BEARER_TOKEN is set."""
import logging
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.crawlers.base import Collector
from app.crawlers.twikit_x import _has_indic, _or_group
from app.ml.geo import city_search_terms, infer_city
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")
API = "https://api.twitter.com/2/tweets/search/recent"


def _build_query(watch_terms: list[str]) -> str:
    """City mentions (any script) OR inherently-local Indic-script watch
    terms — never a bare OR of Latin watch terms, which matches worldwide."""
    cities = [t for t in city_search_terms() if t.lower() != "surat"]
    indic = [t for t in watch_terms if _has_indic(t)]
    group = _or_group(cities + indic, 460)
    return f"({group}) -is:retweet"


class XCollector(Collector):
    name = "X"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._since_id: str | None = None

    def is_configured(self) -> bool:
        return bool(settings.X_BEARER_TOKEN)

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        query = _build_query(watch_terms)
        params = {
            "query": query, "max_results": 25,
            "tweet.fields": "created_at,public_metrics,lang,entities",
            "expansions": "author_id",
            "user.fields": "public_metrics,verified,created_at,name,username",
        }
        if self._since_id:
            params["since_id"] = self._since_id
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(API, params=params,
                                     headers={"Authorization": f"Bearer {settings.X_BEARER_TOKEN}"})
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            log.warning("X collect failed: %s", exc)
            return []

        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        posts: list[RawPost] = []
        for t in data.get("data", []):
            self._since_id = max(self._since_id or "0", t["id"])
            if infer_city(t["text"]) is None and not _has_indic(t["text"]):
                continue  # off-scope: no target city, no local script
            u = users.get(t.get("author_id"), {})
            metrics = t.get("public_metrics", {})
            created = u.get("created_at")
            age = 365
            if created:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
            tags = [h["tag"] for h in t.get("entities", {}).get("hashtags", [])]
            posts.append(RawPost(
                platform="X",
                author_handle=u.get("username", "unknown"), author_name=u.get("name", ""),
                author_followers=u.get("public_metrics", {}).get("followers_count", 0),
                author_verified=u.get("verified", False), author_account_age_days=age,
                text=t["text"], hashtags=tags,
                engagement={"likes": metrics.get("like_count", 0), "shares": metrics.get("retweet_count", 0),
                            "comments": metrics.get("reply_count", 0), "views": metrics.get("impression_count", 0)},
                url=f"https://x.com/{u.get('username', 'i')}/status/{t['id']}",
                created_at=datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                if t.get("created_at") else None,
            ))
        return posts
