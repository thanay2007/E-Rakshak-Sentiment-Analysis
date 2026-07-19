"""Reddit adapter — official OAuth2 API (oauth.reddit.com), keyless fallback
to Reddit's official RSS feeds, last resort PullPush.

With REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET set it authenticates via the
client-credentials grant of a Reddit "script" app (100 req/min quota).

Without credentials it reads the official Atom feeds (r/<sub>/new.rss) —
Reddit serves those to RSS-reader User-Agents even though it 403-blocks the
public .json listings for non-browser clients. RSS is live (no lag) but
carries no score/comment counts. PullPush (the community Pushshift successor)
remains as a last resort, but its index stopped updating around May 2025, so
anything it returns is treated as historical.

All modes combine the two collection strategies:
  1. Seed subreddits (REDDIT_SUBREDDITS) — newest posts of each target-city
     sub, geo-tagged via the optional :City suffix.
  2. Watchlist search — keyword search over the analyst watchlist.
"""
import asyncio
import html as html_lib
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.crawlers.base import Collector
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
RSS_BASE = "https://www.reddit.com"
PULLPUSH = "https://api.pullpush.io/reddit/search/submission/"

_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")


class RedditCollector(Collector):
    name = "Reddit"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._token: str = ""
        self._token_expires: float = 0.0
        self._rss_cursor = 0  # round-robin position over the seed subreddits

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
        posts, rss_ok = await self._collect_rss(watch_terms)
        if rss_ok:  # empty-after-dedup still counts — don't fall back to stale data
            return posts
        return await self._collect_pullpush(watch_terms)

    # ── keyless mode 1: official Atom feeds (live data) ──────────────────

    def _rss_entry_to_post(self, entry: ET.Element, city: str) -> RawPost | None:
        eid = (entry.findtext(f"{_ATOM}id") or "").removeprefix("t3_")
        if not eid or eid in self._seen:
            return None
        self._seen.add(eid)
        title = entry.findtext(f"{_ATOM}title") or ""
        author = (entry.findtext(f"{_ATOM}author/{_ATOM}name") or "unknown").removeprefix("/u/")
        link_el = entry.find(f"{_ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        published = entry.findtext(f"{_ATOM}published") or ""
        sub = ""
        cat = entry.find(f"{_ATOM}category")
        if cat is not None:
            sub = cat.get("term", "")
        # content is HTML: selftext lives in <div class="md">…</div>, followed
        # by "submitted by /u/x [link] [comments]" boilerplate we don't want
        raw = entry.findtext(f"{_ATOM}content") or ""
        body = html_lib.unescape(raw)
        body = body.split("submitted by")[0]
        body = _TAG_RE.sub(" ", body)
        body = html_lib.unescape(body).replace("&#32;", " ")
        body = re.sub(r"\s+", " ", body).strip()
        text = f"{title} {body[:400]}".strip()
        if not text:
            return None
        created = None
        if published:
            try:
                created = datetime.fromisoformat(published).astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                pass
        thumb = entry.find("{http://search.yahoo.com/mrss/}thumbnail")
        media = [thumb.get("url")] if thumb is not None and thumb.get("url") else []
        return RawPost(
            platform="Reddit",
            author_handle=author, author_name=author,
            text=text,
            location=city,
            hashtags=[sub] if sub else [],
            engagement={"likes": 0, "shares": 0, "comments": 0, "views": 0},
            url=link,
            media_urls=media,
            created_at=created,
        )

    def _rss_to_posts(self, xml_text: str, city: str) -> list[RawPost]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            log.warning("Reddit RSS parse failed: %s", exc)
            return []
        return [p for e in root.iter(f"{_ATOM}entry")
                if (p := self._rss_entry_to_post(e, city))]

    async def _collect_rss(self, watch_terms: list[str]) -> tuple[list[RawPost], bool]:
        """Returns (posts, ok) — ok is True when at least one feed request
        succeeded, so an empty-after-dedup tick doesn't trigger the stale
        PullPush fallback."""
        posts: list[RawPost] = []
        ok = False
        # Reddit serves feeds to RSS readers but 403s browser-imitating bots —
        # an honest reader-style UA is what makes this endpoint work
        headers = {"User-Agent": f"{settings.REDDIT_USER_AGENT} (rss reader)"}

        # Reddit rate-limits RSS to a couple of requests per burst — walk the
        # seed subs round-robin, 2 per cycle, plus the watchlist search when
        # the cursor wraps. Full coverage every few cycles instead of a 429
        # storm every tick.
        subs = settings.REDDIT_SUBREDDITS
        batch = [subs[(self._rss_cursor + i) % len(subs)] for i in range(min(2, len(subs)))]
        wrapped = self._rss_cursor + 2 >= len(subs)
        self._rss_cursor = (self._rss_cursor + 2) % max(len(subs), 1)

        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                for sub, city in batch:
                    try:
                        r = await client.get(f"{RSS_BASE}/r/{sub}/new.rss",
                                             params={"limit": 20}, headers=headers)
                        r.raise_for_status()
                        posts.extend(self._rss_to_posts(r.text, city))
                        ok = True
                    except Exception as exc:
                        log.warning("Reddit RSS collect failed for r/%s: %s", sub, exc)
                    await asyncio.sleep(3)

                if watch_terms and wrapped:
                    try:
                        q = " OR ".join(watch_terms[:6])
                        r = await client.get(f"{RSS_BASE}/search.rss",
                                             params={"q": q, "sort": "new", "limit": 20},
                                             headers=headers)
                        r.raise_for_status()
                        posts.extend(self._rss_to_posts(r.text, city=""))
                        ok = True
                    except Exception as exc:
                        log.warning("Reddit RSS search failed: %s", exc)
        except Exception as exc:
            log.warning("Reddit RSS collect failed: %s", exc)
        return posts, ok

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
