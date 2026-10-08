"""YouTube via ScrapingBee's YouTube scraper API
(github.com/ScrapingBee/youtube-scraper-api).

Preferred over the Data API adapter (crawlers/youtube.py) whenever
SCRAPINGBEE_API_KEY is set. ScrapingBee runs the proxies, the browser and the
parsing; this module only calls two of its endpoints:

  * ``/api/v1/youtube/search``   — a query in, a page of results out (5 credits)
  * ``/api/v1/youtube/metadata`` — one video's full description, likes, views,
    upload date and channel (credits per ScrapingBee's request builder)

What it searches is exactly what the Data API adapter searches — the same
watchlist × city rotation (`youtube.next_targets`) and the same relevance test
(`youtube._is_relevant`), so swapping the route never changes which videos
reach an officer, only how they are fetched.

ScrapingBee has no comments endpoint. Comments, replies and the full video
details come from YouTube's own web routes instead (crawlers/youtube_web.py),
which are free — so the credits go on the searches, and metadata is bought
only for a video whose watch page could not be read.

Credits are money, and a free account starts with 1,000 in total, so spending
is capped per day (SCRAPINGBEE_DAILY_CREDITS) and paid details are bought only
for the first few results of each search. A video seen once is never paid for
again in the life of the process.

The response shapes are parsed defensively. ScrapingBee documents the search
response two ways — a ``results`` list of YouTube's own renderer objects
(``videoId``, ``title.runs``, ``longBylineText`` …) and a ``videos`` list of
plain ``title``/``link`` pairs — and both are accepted.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.crawlers import youtube_web
from app.crawlers.base import Collector
from app.crawlers.youtube import _is_relevant, _norm, next_targets
# The parsers are shared with the keyless route, whose search returns the same
# renderer objects; re-exported here because this is where they started.
from app.crawlers.youtube_web import (_channel, _count, _snippet, _text,  # noqa: F401
                                      _thumbnail, _video_id, _when, thread_posts,
                                      video_post)
from app.ml.geo import infer_city
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

SEARCH_URL = "https://app.scrapingbee.com/api/v1/youtube/search"
METADATA_URL = "https://app.scrapingbee.com/api/v1/youtube/metadata"
TIMEOUT = 60  # ScrapingBee renders the page behind each call; seconds, not ms
# How long a refused key or an empty credit balance keeps this route offline.
# Long enough that the Data API adapter takes over for real, short enough that
# a topped-up account is picked up the same day without a restart.
REFUSED_RETRY_HOURS = 6

# The daily credit budget resets at midnight IST — this is an Indian deployment
# and ScrapingBee's own counter is monthly, so any fixed boundary will do.
_BUDGET_TZ = ZoneInfo("Asia/Kolkata")


class Unauthorised(RuntimeError):
    """ScrapingBee refused the key — nothing else this cycle will work."""


class ScrapingBeeYouTubeCollector(Collector):
    name = "YouTube (ScrapingBee)"
    min_interval_seconds = settings.YOUTUBE_MIN_INTERVAL_SECONDS
    # Each call renders a real page on ScrapingBee's side and can take tens of
    # seconds; a cycle is a few searches plus a few detail reads, plus the free
    # watch-page and comment reads for every result.
    timeout_seconds = 120 + TIMEOUT * settings.YOUTUBE_TERMS_PER_CYCLE * (
        1 + settings.SCRAPINGBEE_YT_DETAILS_PER_SEARCH) + 240

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._seen_comments: set[str] = set()
        self._cursor = 0
        self._spent = 0
        self._budget_day = None
        # Why the adapter stopped working, for the sources panel, and when.
        self._error = ""
        self._refused_at = 0.0

    def is_configured(self) -> bool:
        if not settings.SCRAPINGBEE_API_KEY:
            return False
        # A refused key reports the platform offline (or hands it to the Data
        # API adapter, if one is configured) rather than staying green while
        # every call fails.
        return not (self._refused_at and
                    time.monotonic() - self._refused_at < REFUSED_RETRY_HOURS * 3600)

    def status_detail(self) -> str:
        return self._error

    # ── credit ledger ───────────────────────────────────────────────────────

    def _roll_day(self) -> None:
        today = datetime.now(_BUDGET_TZ).date()
        if self._budget_day != today:
            if self._budget_day is not None:
                log.info("ScrapingBee: daily credit window rolled over (spent %d)",
                         self._spent)
            self._budget_day = today
            self._spent = 0

    def _afford(self, credits: int) -> bool:
        if self._spent + credits > settings.SCRAPINGBEE_DAILY_CREDITS:
            return False
        self._spent += credits
        return True

    def credit_status(self) -> dict:
        self._roll_day()
        return {"spent": self._spent, "budget": settings.SCRAPINGBEE_DAILY_CREDITS,
                "remaining": max(0, settings.SCRAPINGBEE_DAILY_CREDITS - self._spent)}

    # ── HTTP ────────────────────────────────────────────────────────────────

    async def _get(self, client: httpx.AsyncClient, url: str, params: dict) -> dict:
        """One authenticated call. The key goes in the Authorization header,
        not the query string, so it never lands in an access or proxy log."""
        response = await client.get(
            url, params=params,
            headers={"Authorization": f"Bearer {settings.SCRAPINGBEE_API_KEY}"})
        if response.status_code in (401, 403):
            raise Unauthorised(f"ScrapingBee refused the API key "
                               f"(HTTP {response.status_code})")
        if response.status_code == 402:
            raise Unauthorised("ScrapingBee account is out of credits (HTTP 402)")
        response.raise_for_status()
        return response.json()

    async def _search(self, client: httpx.AsyncClient, query: str) -> list[dict]:
        payload = await self._get(client, SEARCH_URL, {
            "search": query,
            "type": "video",
            # The Data API adapter's 7-day window, in ScrapingBee's terms.
            "upload_date": "this_week",
            "sort_by": "relevance",
        })
        items = payload.get("results") or payload.get("videos") or []
        return [i for i in items if isinstance(i, dict)]

    async def _metadata(self, client: httpx.AsyncClient, video_id: str) -> dict:
        try:
            return await self._get(client, METADATA_URL, {"video_id": video_id})
        except Unauthorised:
            raise
        except Exception as exc:
            log.warning("ScrapingBee: metadata for %s failed: %s", video_id, exc)
            return {}

    async def _watch_page(self, web: youtube_web.WebClient | None, video_id: str) -> dict:
        """The free watch-page read, or {} — never fatal to the paid route."""
        if web is None:
            return {}
        try:
            return await web.video(video_id)
        except youtube_web.Blocked:
            raise
        except Exception as exc:
            log.debug("ScrapingBee: watch page for %s unreadable: %s", video_id, exc)
            return {}

    # ── mapping ─────────────────────────────────────────────────────────────

    def _to_post(self, video_id: str, item: dict, meta: dict,
                 page: dict | None = None) -> RawPost | None:
        """Paid metadata first, then the free watch page, then the search
        result itself — whichever has the field."""
        page = page or {}
        channel_id, channel_name = _channel(item)
        return video_post(
            video_id,
            title=_text(meta.get("title")) or page.get("title") or _text(item.get("title")),
            description=(_text(meta.get("description")) or page.get("description")
                         or _snippet(item)),
            channel_id=str(meta.get("channel_id") or meta.get("channelId")
                           or page.get("channel_id") or channel_id),
            channel_name=(_text(meta.get("channel_title") or meta.get("channel")
                                or meta.get("uploader"))
                          or page.get("channel_name") or channel_name),
            subscribers=(_count(meta.get("channel_follower_count")
                                or meta.get("subscriber_count") or 0)
                         or page.get("subscribers", 0)),
            verified=page.get("verified", False),
            views=(_count(meta.get("view_count") or 0) or page.get("views")
                   or _count(item.get("viewCountText") or item.get("shortViewCountText")
                             or item.get("views") or 0)),
            likes=_count(meta.get("like_count") or 0) or page.get("likes", 0),
            comments=_count(meta.get("comment_count") or 0),
            created=(_when(meta.get("upload_date") or meta.get("publish_date"))
                     or page.get("published")
                     or _when(item.get("publishedTimeText") or item.get("published_time"))),
            tags=[str(t) for t in meta.get("tags") or []],
            thumbnails=_thumbnail(meta) or _thumbnail(item),
        )

    # ── collection ──────────────────────────────────────────────────────────

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        self._roll_day()
        targets, self._cursor = next_targets(watch_terms, self._cursor)
        posts: list[RawPost] = []
        dropped = 0
        comments = 0
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client, \
                    httpx.AsyncClient(timeout=youtube_web.TIMEOUT, headers=youtube_web.HEADERS,
                                      follow_redirects=True) as yt:
                web = youtube_web.WebClient(yt) if settings.YOUTUBE_WEB_ENABLED else None
                for term, city in targets:
                    if not self._afford(settings.SCRAPINGBEE_YT_SEARCH_CREDITS):
                        log.info("ScrapingBee: daily credit budget spent (%d) — "
                                 "pausing YouTube until tomorrow", self._spent)
                        break
                    query = term if infer_city(term) else f"{term} {city}"
                    try:
                        items = await self._search(client, query)
                    except Unauthorised:
                        raise
                    except Exception as exc:
                        log.warning("ScrapingBee: search '%s' failed: %s", query, exc)
                        continue

                    detailed = 0
                    for item in items:
                        video_id = _video_id(item)
                        if not video_id or video_id in self._seen:
                            continue
                        try:
                            page = await self._watch_page(web, video_id)
                        except youtube_web.Blocked as exc:
                            # Comments stop for this cycle; the paid route goes on.
                            log.warning("ScrapingBee: %s — no comments this cycle", exc)
                            web, page = None, {}
                        meta: dict = {}
                        if (not page
                                and detailed < settings.SCRAPINGBEE_YT_DETAILS_PER_SEARCH
                                and self._afford(settings.SCRAPINGBEE_YT_METADATA_CREDITS)):
                            detailed += 1
                            meta = await self._metadata(client, video_id)
                        post = self._to_post(video_id, item, meta, page)
                        self._seen.add(video_id)
                        if post is None:
                            continue
                        # The same relevance gate as the Data API adapter: a
                        # result that names neither the term nor a watched
                        # city is somebody else's video, in any language —
                        # and so are its comments.
                        if not _is_relevant(term, _norm(post.text + " " + post.author_name)):
                            dropped += 1
                            continue
                        posts.append(post)
                        if web is not None and page.get("comments_token"):
                            try:
                                thread = await thread_posts(web, post, page["comments_token"],
                                                            self._seen_comments)
                            except youtube_web.Blocked as exc:
                                log.warning("ScrapingBee: %s — no comments this cycle", exc)
                                web, thread = None, []
                            comments += len(thread)
                            posts += thread
            self._error = ""
            self._refused_at = 0.0
        except Unauthorised as exc:
            self._error = str(exc)
            self._refused_at = time.monotonic()
            log.warning("ScrapingBee YouTube: %s", exc)
        except Exception as exc:
            log.warning("ScrapingBee YouTube collect failed: %s", exc)

        if dropped:
            log.info("ScrapingBee YouTube: dropped %d results unrelated to the "
                     "query or the city (kept %d)", dropped, len(posts) - comments)
        log.info("ScrapingBee YouTube: %d videos + %d comments/replies",
                 len(posts) - comments, comments)
        return posts
