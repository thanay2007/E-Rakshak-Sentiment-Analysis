"""Facebook adapter — official Graph API over a seed-page list.

Implements the seed-URL strategy: instead of crawling the open web, monitor
the top public pages for each target city (news outlets, civic bodies, big
community pages). Configure FB_ACCESS_TOKEN plus FB_PAGE_IDS, e.g.
    FB_PAGE_IDS=tv9gujarati:Ahmedabad,SuratMunicipalCorporation:Surat
The optional :City suffix geo-tags every post collected from that page.

Token notes: reading pages you manage needs a Page token; reading arbitrary
public pages needs an app with the Page Public Content Access feature
approved by Meta. Both work through the same endpoints used here.
"""
import asyncio
import logging
from datetime import datetime

import httpx

from app.config import settings
from app.crawlers.base import Collector
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")


def _iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("+0000", "+00:00")).replace(tzinfo=None)


class FacebookCollector(Collector):
    name = "Facebook"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._page_meta: dict[str, dict] = {}  # page id -> {name, username, followers}

    def is_configured(self) -> bool:
        return bool(settings.FB_ACCESS_TOKEN and settings.FB_PAGE_IDS)

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{settings.FB_API_VERSION}"

    async def _meta(self, client: httpx.AsyncClient, page: str) -> dict:
        if page not in self._page_meta:
            r = await client.get(f"{self._base}/{page}", params={
                "fields": "id,name,username,followers_count,fan_count",
                "access_token": settings.FB_ACCESS_TOKEN,
            })
            r.raise_for_status()
            d = r.json()
            self._page_meta[page] = {
                "name": d.get("name", page),
                "username": d.get("username") or page,
                "followers": d.get("followers_count") or d.get("fan_count") or 0,
            }
        return self._page_meta[page]

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        posts: list[RawPost] = []
        async with httpx.AsyncClient(timeout=20) as client:
            for page, city in settings.FB_PAGE_IDS:
                try:
                    meta = await self._meta(client, page)
                    r = await client.get(f"{self._base}/{page}/posts", params={
                        "fields": "id,message,created_time,permalink_url,"
                                  "shares,reactions.summary(true).limit(0),"
                                  "comments.summary(true).limit(0)",
                        "limit": 25,
                        "access_token": settings.FB_ACCESS_TOKEN,
                    })
                    r.raise_for_status()
                    items = r.json().get("data", [])
                except Exception as exc:
                    log.warning("Facebook collect failed for page %s: %s", page, exc)
                    continue

                for it in items:
                    pid = it.get("id", "")
                    text = (it.get("message") or "").strip()
                    if not pid or pid in self._seen or not text:
                        continue
                    self._seen.add(pid)
                    posts.append(RawPost(
                        platform="Facebook",
                        author_handle=meta["username"], author_name=meta["name"],
                        author_followers=meta["followers"],
                        text=text[:1000],
                        location=city,
                        engagement={
                            "likes": (it.get("reactions", {}).get("summary", {}) or {}).get("total_count", 0),
                            "shares": (it.get("shares") or {}).get("count", 0),
                            "comments": (it.get("comments", {}).get("summary", {}) or {}).get("total_count", 0),
                            "views": 0,
                        },
                        url=it.get("permalink_url", ""),
                        created_at=_iso(it.get("created_time")),
                    ))
                await asyncio.sleep(1)  # gap between page queries inside one batch
        return posts
