"""YouTube without a key — the routes youtube.com's own web client calls
(``/youtubei/v1/*``, "innertube").

Two jobs:

  * **Comments for the ScrapingBee route.** ScrapingBee has no comments
    endpoint, and on a news video the caption is the headline while the
    reaction is in the comments. ``video()`` + ``comments()`` + ``replies()``
    here are free, so the ScrapingBee adapter uses them for every video it
    finds and only spends credits on the search itself.
  * **A keyless YouTube adapter** (``YouTubeWebCollector``), last in the
    registry's preference order. A deployment with no ScrapingBee key and no
    Data API key would otherwise have no YouTube at all.

What it reads, per cycle:

  * search — the same watchlist × city rotation and the same relevance test as
    the other two adapters (`youtube.next_targets`, `youtube._is_relevant`);
  * each new video's full description, channel, subscribers, views and likes
    (``next`` with a videoId);
  * the top comment threads under it, and the replies under the busiest of
    those threads — a comment is a post in its own right, as everywhere else;
  * the newest uploads of channels an officer put on the watchlist;
  * a second look at the most-discussed videos of the last two days, because a
    video found an hour after upload has few comments yet. Ingestion dedupes on
    author + text, so re-reading a thread only stores what is new.

Response shapes were taken from live calls (October 2026). YouTube renames
renderers from time to time, so every parser walks the payload for the key it
needs instead of following a fixed path, and reads both the current comment
shape (``commentEntityPayload``) and the older one (``commentRenderer``).
A shape it cannot read yields nothing for that item — never an exception.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import settings
from app.crawlers.base import Collector
from app.crawlers.common import extract_hashtags
from app.crawlers.common import rotate as _rotate
from app.crawlers.youtube import _is_relevant, _norm, next_targets
from app.ml.geo import dominant_city, infer_city
from app.schemas import RawPost
from app.services.watch_targets import watched_accounts

log = logging.getLogger("sentinel.crawlers")

API = "https://www.youtube.com/youtubei/v1/"
CONTEXT = {"client": {"clientName": "WEB", "clientVersion": "2.20251001.00.00",
                      "hl": "en", "gl": "IN"}}
HEADERS = {
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "content-type": "application/json",
    "origin": "https://www.youtube.com",
    "accept-language": "en-IN,en;q=0.9",
}
TIMEOUT = 30
#: Search filter "uploaded this week" + "type video" — the Data API adapter's
#: 7-day window, in the web client's terms.
SEARCH_THIS_WEEK_VIDEOS = "EgQIAxAB"
#: A channel's "Videos" tab, newest first.
CHANNEL_VIDEOS_TAB = "EgZ2aWRlb3PyBgQKAjoA"
#: How long the route stays parked after YouTube answers 429.
BLOCKED_COOLDOWN_MINUTES = 60
#: Pause between requests, seconds. YouTube tolerates far more than this; the
#: gap is what keeps a long watchlist from looking like a burst.
REQUEST_GAP = (0.8, 2.0)
#: Videos re-read for new comments, and how far back they are remembered.
REVISIT_WINDOW = timedelta(days=2)

_COUNT_RE = re.compile(r"([\d.,]+)\s*([KMB]|lakh|crore)?", re.IGNORECASE)
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9, "lakh": 1e5, "crore": 1e7}
_RELATIVE_RE = re.compile(
    r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE)
_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400,
                 "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}
_ABS_DATE_RE = re.compile(r"([A-Z][a-z]{2,8})\s+(\d{1,2}),\s+(\d{4})")
_OTHERS_LIKE_RE = re.compile(r"along with ([\d,]+) other", re.IGNORECASE)
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
#: A watchlist entry YouTube could plausibly know: a channel id or a handle.
_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_HANDLE_RE = re.compile(r"^@?[A-Za-z0-9._-]{3,30}$")


class Blocked(RuntimeError):
    """YouTube answered 429 or a consent wall — stop asking for a while."""


# ── text helpers (shared with youtube_scrapingbee.py) ───────────────────────

def _text(value) -> str:
    """YouTube renderer text in any of its shapes → plain string.

    A field can be a bare string, ``{"simpleText": ...}``, ``{"runs": [{"text":
    ...}]}``, ``{"content": ...}`` (view models), or a list of any of these.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(v) for v in value).strip()
    if isinstance(value, dict):
        if "simpleText" in value:
            return str(value["simpleText"] or "")
        if "runs" in value:
            return "".join(str(r.get("text", "")) for r in value["runs"] or []
                           if isinstance(r, dict))
        for key in ("snippetText", "text", "content"):
            if key in value:
                return _text(value[key])
    return ""


def _count(value) -> int:
    """"1.2K views", "12,345 views", "3.4 lakh views", 987 → an int."""
    if isinstance(value, (int, float)):
        return int(value)
    m = _COUNT_RE.search(_text(value).replace(" ", " "))
    if not m:
        return 0
    try:
        number = float(m.group(1).replace(",", ""))
    except ValueError:
        return 0
    return int(number * _SCALE.get((m.group(2) or "").lower(), 1))


def _when(value, now: datetime | None = None) -> datetime | None:
    """An upload or comment date in any shape YouTube shows it → naive UTC.

    "2023-01-01", an ISO timestamp, "20230101", "Oct 5, 2026", "Premiered Oct
    5, 2026", "3 days ago", "Streamed 2 hours ago", "2 days ago (edited)".
    """
    text = _text(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass
    if re.fullmatch(r"\d{8}", text):  # yt-dlp style 20230101
        return datetime.strptime(text, "%Y%m%d")
    m = _RELATIVE_RE.search(text)
    if m:
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        return now - timedelta(seconds=int(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()])
    m = _ABS_DATE_RE.search(text)
    if m:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(" ".join(m.groups()), fmt)
            except ValueError:
                continue
    return None


def _walk(obj, key: str, out: list | None = None) -> list:
    """Every value stored under `key`, anywhere in a payload, in page order."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                out.append(v)
            if isinstance(v, (dict, list)):
                _walk(v, key, out)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                _walk(v, key, out)
    return out


def _first(obj, key: str):
    found = _walk(obj, key)
    return found[0] if found else None


# ── search-result parsers (ScrapingBee returns the same renderer shapes) ──

def _video_id(item: dict) -> str:
    vid = str(item.get("videoId") or item.get("video_id") or item.get("id") or "")
    if _VIDEO_ID_RE.match(vid):
        return vid
    link = str(item.get("link") or item.get("url") or "")
    if link:
        parsed = urlparse(link)
        if (v := parse_qs(parsed.query).get("v")):
            return v[0]
        tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]   # youtu.be/<id>, /shorts/<id>
        if _VIDEO_ID_RE.match(tail):
            return tail
    return ""


def _channel(item: dict) -> tuple[str, str]:
    """(channel id, channel name) from a search result."""
    byline = item.get("longBylineText") or item.get("ownerText") or item.get("shortBylineText")
    name = _text(byline) or _text(item.get("channel") or item.get("channel_title")
                                  or item.get("channelTitle"))
    channel_id = str(item.get("channel_id") or item.get("channelId") or "")
    if not channel_id and isinstance(byline, dict):
        for run in byline.get("runs") or []:
            browse = (((run or {}).get("navigationEndpoint") or {})
                      .get("browseEndpoint") or {})
            if browse.get("browseId"):
                channel_id = str(browse["browseId"])
                break
    if isinstance(item.get("channel"), dict):
        channel_id = channel_id or str(item["channel"].get("id") or "")
        name = name or _text(item["channel"].get("name"))
    return channel_id, name


def _snippet(item: dict) -> str:
    """Whatever description text a search result carries (often a fragment)."""
    for key in ("descriptionSnippet", "detailedMetadataSnippets", "description",
                "snippet"):
        if (text := _text(item.get(key))):
            return text
    return ""


def _thumbnail(item: dict) -> list[str]:
    if (url := item.get("thumbnail_url")):
        return [str(url)]
    thumbs = (item.get("thumbnail") or {}).get("thumbnails") if isinstance(
        item.get("thumbnail"), dict) else None
    if thumbs:
        return [str(thumbs[-1].get("url", ""))] if thumbs[-1].get("url") else []
    return []


# ── the client ──────────────────────────────────────────────────────────────

class WebClient:
    """The handful of innertube calls this backend makes. One per cycle."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _post(self, endpoint: str, body: dict) -> dict:
        response = await self._client.post(
            f"{API}{endpoint}", params={"prettyPrint": "false"},
            json={"context": CONTEXT, **body})
        if response.status_code == 429:
            raise Blocked("YouTube rate-limited the web route (HTTP 429)")
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        if "consent.youtube.com" in str(response.url):
            raise Blocked("YouTube served its consent wall")
        return response.json()

    async def search(self, query: str) -> list[dict]:
        """videoRenderer objects for this week's videos matching `query` —
        the same renderer shape ScrapingBee's ``results`` list carries."""
        data = await self._post("search", {"query": query,
                                           "params": SEARCH_THIS_WEEK_VIDEOS})
        return [v for v in _walk(data, "videoRenderer") if isinstance(v, dict)]

    async def video(self, video_id: str) -> dict:
        """One video's watch-page details, plus the token for its comments.

        {} when the video is gone or its page could not be read.
        """
        data = await self._post("next", {"videoId": video_id})
        primary = _first(data, "videoPrimaryInfoRenderer") or {}
        secondary = _first(data, "videoSecondaryInfoRenderer") or {}
        if not primary:
            return {}
        owner = (secondary.get("owner") or {}).get("videoOwnerRenderer") or {}
        likes = 0
        for label in _walk(primary, "accessibilityText"):
            if (m := _OTHERS_LIKE_RE.search(str(label))):
                likes = int(m.group(1).replace(",", "")) + 1
                break
        token = ""
        for section in _walk(data, "itemSectionRenderer"):
            if section.get("sectionIdentifier") == "comment-item-section":
                token = next(iter(_walk(section, "token")), "")
                break
        badges = [(b.get("metadataBadgeRenderer") or {}).get("style", "")
                  for b in owner.get("badges") or []]
        return {
            "title": _text(primary.get("title")),
            "description": _text(secondary.get("attributedDescription"))
                           or _text(secondary.get("description")),
            "channel_id": next(iter(_walk(owner.get("title"), "browseId")), ""),
            "channel_name": _text(owner.get("title")),
            "subscribers": _count(owner.get("subscriberCountText")),
            "verified": any("VERIFIED" in b for b in badges),
            "views": _count(((primary.get("viewCount") or {})
                             .get("videoViewCountRenderer") or {}).get("viewCount")),
            "likes": likes,
            "published": (_when(primary.get("dateText"))
                          or _when(primary.get("relativeDateText"))),
            "comments_token": token,
        }

    async def comments(self, token: str, limit: int) -> tuple[list[dict], int]:
        """Top-level comments of the first thread page, and the video's total
        comment count from the thread header (0 when it is not shown)."""
        if not token or limit <= 0:
            return [], 0
        data = await self._post("next", {"continuation": token})
        header = _first(data, "commentsHeaderRenderer") or {}
        total = _count(header.get("countText") or header.get("commentsCount"))
        return [c for c in _parse_comments(data) if c["level"] == 0][:limit], total

    async def replies(self, token: str, limit: int) -> list[dict]:
        if not token or limit <= 0:
            return []
        data = await self._post("next", {"continuation": token})
        return [c for c in _parse_comments(data) if c["level"] > 0][:limit]

    async def channel(self, handle_or_id: str) -> dict:
        """A watched channel's id, name and newest uploads.

        {"id", "name", "uploads": [{"video_id", "title", "views", "published"}]},
        or {} when YouTube has no such channel.
        """
        if _CHANNEL_ID_RE.match(handle_or_id):
            browse_id = handle_or_id
        else:
            handle = handle_or_id if handle_or_id.startswith("@") else f"@{handle_or_id}"
            resolved = await self._post("navigation/resolve_url",
                                        {"url": f"https://www.youtube.com/{handle}"})
            browse_id = next((b.get("browseId") for b in _walk(resolved, "browseEndpoint")
                              if str(b.get("browseId", "")).startswith("UC")), "")
            if not browse_id:
                return {}
        data = await self._post("browse", {"browseId": browse_id,
                                           "params": CHANNEL_VIDEOS_TAB})
        meta = _first(data, "channelMetadataRenderer") or {}
        uploads = []
        for lockup in _walk(data, "lockupViewModel"):
            vid = str(lockup.get("contentId") or "")
            if not _VIDEO_ID_RE.match(vid) or "VIDEO" not in str(lockup.get("contentType", "")):
                continue
            md = ((lockup.get("metadata") or {}).get("lockupMetadataViewModel") or {})
            parts = [_text(p.get("text")) for row in _walk(md, "metadataParts")
                     for p in row or [] if isinstance(p, dict)]
            uploads.append({
                "video_id": vid,
                "title": _text(md.get("title")),
                "views": next((_count(p) for p in parts if "view" in p.lower()), 0),
                "published": next((w for p in parts if (w := _when(p))), None),
            })
        for renderer in _walk(data, "videoRenderer"):   # the older tab shape
            if _VIDEO_ID_RE.match(str(renderer.get("videoId", ""))):
                uploads.append({
                    "video_id": renderer["videoId"],
                    "title": _text(renderer.get("title")),
                    "views": _count(renderer.get("viewCountText")),
                    "published": _when(renderer.get("publishedTimeText")),
                })
        return {"id": meta.get("externalId") or browse_id,
                "name": meta.get("title") or handle_or_id.lstrip("@"),
                "uploads": uploads}


def _parse_comments(data: dict) -> list[dict]:
    """Comment entities in page order, each as
    {id, text, author, author_id, verified, likes, replies, published, level,
    reply_token}. Reads both the current and the older payload shape."""
    reply_tokens: dict[str, str] = {}
    for thread in _walk(data, "commentThreadRenderer"):
        cid = (_first(thread.get("commentViewModel") or {}, "commentId")
               or _first(thread.get("comment") or {}, "commentId") or "")
        token = next(iter(_walk(thread.get("replies") or {}, "token")), "")
        if cid and token:
            reply_tokens[cid] = token

    out: list[dict] = []
    for entity in _walk(data, "commentEntityPayload"):
        props = entity.get("properties") or {}
        author = entity.get("author") or {}
        toolbar = entity.get("toolbar") or {}
        cid = str(props.get("commentId") or "")
        text = _text(props.get("content")).strip()
        if not cid or not text:
            continue
        out.append({
            "id": cid,
            "text": text,
            "author": str(author.get("displayName") or "").strip() or "youtube",
            "author_id": str(author.get("channelId") or ""),
            "verified": bool(author.get("isVerified")),
            "likes": _count(toolbar.get("likeCountNotliked") or 0),
            "replies": _count(toolbar.get("replyCount") or 0),
            "published": _when(props.get("publishedTime")),
            "level": int(props.get("replyLevel") or 0),
            "reply_token": reply_tokens.get(cid, ""),
        })
    if out:
        return out

    for renderer in _walk(data, "commentRenderer"):   # the pre-2024 shape
        cid = str(renderer.get("commentId") or "")
        text = _text(renderer.get("contentText")).strip()
        if not cid or not text:
            continue
        out.append({
            "id": cid,
            "text": text,
            "author": _text(renderer.get("authorText")).strip() or "youtube",
            "author_id": str(((renderer.get("authorEndpoint") or {})
                              .get("browseEndpoint") or {}).get("browseId") or ""),
            "verified": bool(renderer.get("authorCommentBadge")),
            "likes": _count(renderer.get("voteCount") or 0),
            "replies": int(renderer.get("replyCount") or 0),
            "published": _when(renderer.get("publishedTimeText")),
            "level": 1 if "." in cid else 0,
            "reply_token": reply_tokens.get(cid, ""),
        })
    return out


# ── mapping (shared with youtube_scrapingbee.py) ───────────────────────────

def video_post(video_id: str, *, title: str, description: str, channel_id: str,
               channel_name: str, subscribers: int = 0, verified: bool = False,
               views: int = 0, likes: int = 0, comments: int = 0,
               created: datetime | None = None, tags: list[str] | None = None,
               thumbnails: list[str] | None = None) -> RawPost | None:
    """A video as a RawPost, geography from its own text — never from the
    query (see youtube.py for the Moradabad story)."""
    if not (title or description):
        return None
    blob = _norm(" ".join((title, description, " ".join(tags or []), channel_name)))
    hit = dominant_city(blob)
    city, lat, lon = hit if hit else ("", 0.0, 0.0)
    text = f"{title}\n\n{description}".strip()
    return RawPost(
        platform="YouTube",
        author_handle=channel_name or "youtube",
        author_id=channel_id,
        author_name=channel_name,
        author_followers=subscribers,
        author_verified=verified,
        author_account_age_days=0,
        text=text[:4000],
        hashtags=extract_hashtags(text),
        engagement={"likes": likes, "views": views, "comments": comments},
        url=f"https://www.youtube.com/watch?v={video_id}",
        media_urls=thumbnails or [f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"],
        created_at=created,
        location=city,
        latitude=lat,
        longitude=lon,
    )


def comment_post(comment: dict, video: RawPost) -> RawPost:
    """A comment or reply as a RawPost — the Data API adapter's conventions:
    the video's city unless the comment names its own, ``&lc=`` permalink."""
    city, lat, lon = video.location, video.latitude, video.longitude
    if (where := infer_city(comment["text"])):
        city, lat, lon = where
    return RawPost(
        platform="YouTube",
        author_handle=comment["author"],
        author_id=comment["author_id"],
        author_name=comment["author"],
        author_followers=0,  # a commenter's channel is never fetched
        author_verified=comment["verified"],
        author_account_age_days=0,
        text=comment["text"][:2000],
        hashtags=extract_hashtags(comment["text"]),
        engagement={"likes": comment["likes"], "replies": comment["replies"]},
        url=f"{video.url}&lc={comment['id']}",
        created_at=comment["published"],
        location=city,
        latitude=lat,
        longitude=lon,
    )


async def thread_posts(web: WebClient, video: RawPost, token: str,
                       seen: set[str], pause=None) -> list[RawPost]:
    """Comments under one video, and replies under its busiest threads.

    `seen` holds comment ids already turned into posts by this process, so a
    revisit only emits what is new. The video's comment count is raised to the
    thread total when YouTube shows one. Errors cost this video's comments only.
    """
    out: list[RawPost] = []
    try:
        top, total = await web.comments(token, settings.YOUTUBE_COMMENTS_PER_VIDEO)
    except Blocked:
        raise
    except Exception as exc:
        log.warning("YouTube web: comments for %s failed: %s", video.url, exc)
        return out
    video.engagement["comments"] = max(video.engagement.get("comments", 0), total, len(top))
    for c in top:
        if c["id"] not in seen:
            seen.add(c["id"])
            out.append(comment_post(c, video))
    busiest = sorted((c for c in top if c["replies"] > 0 and c["reply_token"]),
                     key=lambda c: c["replies"], reverse=True)
    for c in busiest[:settings.YOUTUBE_REPLY_THREADS_PER_VIDEO]:
        if pause:
            await pause()
        try:
            replies = await web.replies(c["reply_token"], settings.YOUTUBE_REPLIES_PER_THREAD)
        except Blocked:
            raise
        except Exception as exc:
            log.debug("YouTube web: replies under %s failed: %s", c["id"], exc)
            continue
        for r in replies:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(comment_post(r, video))
    return out


# ── the keyless adapter ────────────────────────────────────────────────────

class YouTubeWebCollector(Collector):
    """YouTube videos, comments and replies with no key at all. Last in the
    registry's preference order: used only when neither ScrapingBee nor the
    Data API is configured."""

    name = "YouTube (web)"
    min_interval_seconds = settings.YOUTUBE_MIN_INTERVAL_SECONDS
    timeout_seconds = 300

    def __init__(self) -> None:
        self._cursor = random.randrange(1024)
        self._channel_cursor = 0
        self._seen_videos: set[str] = set()
        self._seen_comments: set[str] = set()
        #: video id → (post, first seen) for the revisit leg.
        self._recent: dict[str, tuple[RawPost, datetime]] = {}
        self._missing_channels: dict[str, float] = {}
        self._blocked_at = 0.0
        self._error = ""

    def is_configured(self) -> bool:
        if not settings.YOUTUBE_WEB_ENABLED:
            return False
        if self._blocked_at and time.monotonic() - self._blocked_at < BLOCKED_COOLDOWN_MINUTES * 60:
            return False
        return True

    def status_detail(self) -> str:
        return self._error

    @staticmethod
    async def _pause() -> None:
        await asyncio.sleep(random.uniform(*REQUEST_GAP))

    async def _read_video(self, web: WebClient, video_id: str, item: dict | None = None,
                          term: str = "") -> list[RawPost]:
        """A new video and its comment threads. With `term`, the video must
        pass the relevance test; a watched channel's uploads need not."""
        item = item or {}
        details = await web.video(video_id)
        await self._pause()
        channel_id, channel_name = _channel(item)
        post = video_post(
            video_id,
            title=details.get("title") or _text(item.get("title")),
            description=details.get("description") or _snippet(item),
            channel_id=details.get("channel_id") or channel_id,
            channel_name=details.get("channel_name") or channel_name,
            subscribers=details.get("subscribers", 0),
            verified=details.get("verified", False),
            views=details.get("views") or _count(item.get("viewCountText")),
            likes=details.get("likes", 0),
            created=details.get("published") or _when(item.get("publishedTimeText")),
        )
        self._seen_videos.add(video_id)
        if post is None:
            return []
        if term and not _is_relevant(term, _norm(post.text + " " + post.author_name)):
            return []
        out = [post]
        token = details.get("comments_token", "")
        if token:
            out += await thread_posts(web, post, token, self._seen_comments, self._pause)
            self._recent[video_id] = (post, datetime.now(timezone.utc).replace(tzinfo=None))
        return out

    async def _search_leg(self, web: WebClient, watch_terms: list[str]) -> list[RawPost]:
        targets, self._cursor = next_targets(watch_terms, self._cursor)
        posts: list[RawPost] = []
        for term, city in targets:
            query = term if infer_city(term) else f"{term} {city}"
            try:
                items = await web.search(query)
            except Blocked:
                raise
            except Exception as exc:
                log.warning("YouTube web: search '%s' failed: %s", query, exc)
                continue
            await self._pause()
            fresh = [(vid, i) for i in items
                     if (vid := str(i.get("videoId") or "")) and vid not in self._seen_videos]
            for vid, item in fresh[:settings.YOUTUBE_WEB_VIDEOS_PER_SEARCH]:
                try:
                    posts += await self._read_video(web, vid, item, term=term)
                except Blocked:
                    raise
                except Exception as exc:
                    log.warning("YouTube web: video %s failed: %s", vid, exc)
        return posts

    async def _channels_leg(self, web: WebClient) -> list[RawPost]:
        budget = settings.YOUTUBE_WATCHED_CHANNELS_PER_CYCLE
        if budget <= 0:
            return []
        try:
            handles = watched_accounts()
        except Exception as exc:
            log.warning("YouTube web: watchlist accounts unavailable: %s", exc)
            return []
        now = time.monotonic()
        usable = sorted({h.strip() for h in handles
                         if (_HANDLE_RE.match(h.strip()) or _CHANNEL_ID_RE.match(h.strip()))
                         and now - self._missing_channels.get(h.strip(), -1e9) > 6 * 3600})
        slice_, self._channel_cursor = _rotate(usable, self._channel_cursor, budget)
        posts: list[RawPost] = []
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
        for handle in slice_:
            try:
                channel = await web.channel(handle)
            except Blocked:
                raise
            except Exception as exc:
                log.warning("YouTube web: channel %s failed: %s", handle, exc)
                continue
            await self._pause()
            if not channel:
                # The watchlist has no platform column — most handles on it
                # are not YouTube channels. Don't ask again for a while.
                self._missing_channels[handle] = now
                continue
            new = [u for u in channel["uploads"]
                   if u["video_id"] not in self._seen_videos
                   and (u["published"] is None or u["published"] >= cutoff)]
            for upload in new[:settings.YOUTUBE_WATCHED_UPLOADS_PER_CHANNEL]:
                try:
                    posts += await self._read_video(web, upload["video_id"])
                except Blocked:
                    raise
                except Exception as exc:
                    log.warning("YouTube web: upload %s failed: %s", upload["video_id"], exc)
        return posts

    async def _revisit_leg(self, web: WebClient, skip: set[str]) -> list[RawPost]:
        """New comments under the busiest videos already read."""
        budget = settings.YOUTUBE_REVISITS_PER_CYCLE
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - REVISIT_WINDOW
        self._recent = {k: v for k, v in self._recent.items() if v[1] >= cutoff}
        if budget <= 0:
            return []
        ranked = sorted((k for k in self._recent if k not in skip),
                        key=lambda k: self._recent[k][0].engagement.get("comments", 0),
                        reverse=True)[:budget]
        posts: list[RawPost] = []
        for vid in ranked:
            video = self._recent[vid][0]
            try:
                token = (await web.video(vid)).get("comments_token", "")
                await self._pause()
                posts += await thread_posts(web, video, token, self._seen_comments, self._pause)
            except Blocked:
                raise
            except Exception as exc:
                log.debug("YouTube web: revisit %s failed: %s", vid, exc)
        return posts

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        posts: list[RawPost] = []
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS,
                                         follow_redirects=True) as client:
                web = WebClient(client)
                before = set(self._recent)
                posts += await self._search_leg(web, watch_terms)
                posts += await self._channels_leg(web)
                posts += await self._revisit_leg(web, skip=set(self._recent) - before)
            self._error = ""
            self._blocked_at = 0.0
        except Blocked as exc:
            self._error = str(exc)
            self._blocked_at = time.monotonic()
            log.warning("YouTube web: %s — parking for %d minutes (kept %d posts)",
                        exc, BLOCKED_COOLDOWN_MINUTES, len(posts))
        except Exception as exc:
            log.warning("YouTube web collect failed: %s", exc)
        videos = sum(1 for p in posts if "&lc=" not in p.url)
        log.info("YouTube web: %d videos + %d comments/replies", videos, len(posts) - videos)
        return posts
