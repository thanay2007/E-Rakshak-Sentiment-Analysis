"""YouTube Data API v3 adapter — video search, comments, and channel OSINT.

Activates when YOUTUBE_API_KEY is set in .env. Searches for videos matching
watch terms and extracts comments for sentiment analysis and OSINT.

Rate limits: 10,000 quota units per day (shared quota for all operations).
  - video search: ~100 units per query
  - comments fetch: ~1 unit per comment
  - channel info: ~2 units per channel
"""
import logging
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.crawlers.base import Collector
from app.ml.geo import CITIES, infer_city
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

# Documented quota costs (units) for the calls this adapter makes.
_COST_SEARCH = 100
_COST_LIST = 1        # videos.list / channels.list / commentThreads.list

# YouTube resets project quota at midnight Pacific, not UTC.
_QUOTA_TZ = ZoneInfo("America/Los_Angeles")


class YouTubeCollector(Collector):
    name = "YouTube"
    min_interval_seconds = settings.YOUTUBE_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self.youtube = None
        self._spent = 0
        self._quota_day = None
        # Where in the watchlist this instance resumes searching. Randomised so a
        # restart-heavy deployment doesn't keep re-searching the same first terms
        # and starving the tail of the list.
        self._cursor = random.randrange(1024)
        self._load_client()

    # ── quota ledger ───────────────────────────────────────────────────────

    def _roll_day(self) -> None:
        today = datetime.now(_QUOTA_TZ).date()
        if self._quota_day != today:
            if self._quota_day is not None:
                log.info("YouTube quota window rolled over (spent %d units)", self._spent)
            self._quota_day = today
            self._spent = 0

    def _afford(self, units: int) -> bool:
        """Reserve `units` against today's budget, or refuse if it would overrun."""
        if self._spent + units > settings.YOUTUBE_DAILY_QUOTA:
            return False
        self._spent += units
        return True

    def _targets(self, watch_terms: list[str]) -> list[tuple[str, str]]:
        """Every (term, city) pair this deployment cares about.

        YouTube has no geo filter worth using — `location` only applies to videos
        that carry coordinates, which almost none do, and regionCode=IN is the
        whole country. So the city is pushed into the query text instead, the
        same city-anchoring the Reddit and Telegram adapters get from their seed
        subreddits and channels. A term that already names a city is searched as
        it stands rather than doubled up into "Surat Ahmedabad".
        """
        pairs: list[tuple[str, str]] = []
        for term in watch_terms:
            hit = infer_city(term)
            if hit:
                pairs.append((term, hit[0]))   # term already names a city
            else:
                pairs.extend((term, city) for city in settings.TARGET_CITIES)
        return pairs

    def _next_targets(self, watch_terms: list[str]) -> list[tuple[str, str]]:
        """The rotating slice of (term, city) pairs to search this cycle."""
        pairs = self._targets(watch_terms)
        if not pairs:
            return []
        n = min(settings.YOUTUBE_TERMS_PER_CYCLE, len(pairs))
        start = self._cursor % len(pairs)
        self._cursor = start + n
        # wrap around the end of the list
        return [pairs[(start + i) % len(pairs)] for i in range(n)]

    def quota_status(self) -> dict:
        self._roll_day()
        return {"spent": self._spent, "budget": settings.YOUTUBE_DAILY_QUOTA,
                "remaining": max(0, settings.YOUTUBE_DAILY_QUOTA - self._spent)}

    def _load_client(self) -> None:
        """Lazy-load YouTube API client."""
        if not self.is_configured():
            return
        try:
            from googleapiclient.discovery import build
            self.youtube = build("youtube", "v3", developerKey=settings.YOUTUBE_API_KEY)
            log.info("YouTube Data API client loaded")
        except Exception as exc:
            log.warning("YouTube client init failed: %s", exc)
            self.youtube = None

    def is_configured(self) -> bool:
        return bool(settings.YOUTUBE_API_KEY)

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        """Search YouTube for videos matching watch terms and extract comments."""
        if not self.youtube:
            return []

        self._roll_day()
        posts: list[RawPost] = []
        # Search for recent videos (published in last 7 days)
        search_after = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        for term, city in self._next_targets(watch_terms):
            if not self._afford(_COST_SEARCH):
                log.info("YouTube daily quota budget spent (%d units) — pausing until reset",
                         self._spent)
                break
            query = term if infer_city(term) else f"{term} {city}"
            lat, lon = CITIES.get(city, (0.0, 0.0))
            try:
                # Search for videos
                search_response = self.youtube.search().list(
                    q=query,
                    part="snippet",
                    type="video",
                    maxResults=10,
                    order="relevance",
                    publishedAfter=search_after,
                    # No relevanceLanguage: the API takes a single ISO-639-1 code,
                    # and a list is a hard 400. Pinning one of en/hi/gu would bias
                    # results away from the other two — the multilingual mix is the
                    # point here. The city in the query anchors the geography.
                    regionCode="IN",
                ).execute()

                items = search_response.get("items", [])
                # videos.list and channels.list both accept up to 50 comma-joined
                # ids for the same 1 unit, so fetch the whole result page at once
                # rather than paying per video.
                stats_by_video = self._batch_stats(
                    [i["id"]["videoId"] for i in items]
                )
                channels = self._batch_channels(
                    {i["snippet"]["channelId"] for i in items}
                )

                for item in items:
                    video_id = item["id"]["videoId"]
                    snippet = item["snippet"]

                    stats = stats_by_video.get(video_id, {})
                    view_count = int(stats.get("viewCount", 0))
                    like_count = int(stats.get("likeCount", 0))
                    comment_count = int(stats.get("commentCount", 0))

                    channel_id = snippet["channelId"]
                    channel_name, channel_subs = channels.get(channel_id, ("", 0))

                    # Create a post for the video itself
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    created = datetime.fromisoformat(
                        snippet["publishedAt"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)

                    posts.append(
                        RawPost(
                            platform="YouTube",
                            author_handle=snippet["channelTitle"],
                            author_name=channel_name or snippet["channelTitle"],
                            author_followers=channel_subs,
                            author_verified=False,
                            author_account_age_days=0,
                            text=snippet["title"] + "\n\n" + snippet["description"],
                            hashtags=[],
                            engagement={
                                "likes": like_count,
                                "views": view_count,
                                "comments": comment_count,
                            },
                            url=url,
                            created_at=created,
                            location=city,
                            latitude=lat,
                            longitude=lon,
                            metadata={"video_id": video_id, "channel_id": channel_id},
                        )
                    )

                    # Fetch and process comments
                    if not self._afford(_COST_LIST):
                        continue
                    try:
                        comments_response = self.youtube.commentThreads().list(
                            videoId=video_id,
                            part="snippet",
                            maxResults=20,
                            order="relevance",
                            # No searchTerms: combined with order it is a hard 400,
                            # and on its own it drops nearly every comment (the term
                            # that matched the *video* rarely recurs in each comment).
                            # Keyword-filtering at collection time is also the exact
                            # evasion route we refuse to open — the NLP pipeline
                            # scores every comment downstream instead.
                            textFormat="plainText",
                        ).execute()

                        for comment_item in comments_response.get("items", []):
                            comment = comment_item["snippet"]["topLevelComment"]["snippet"]
                            author = comment["authorDisplayName"]
                            author_url = comment.get("authorChannelUrl", "")
                            author_channel_id = (
                                comment.get("authorChannelId", {}).get("value", "")
                            )

                            # A comment inherits the city its video was found
                            # under; if the text names a different one, that wins.
                            # infer_city returns (city, lat, lon) or None — the
                            # tuple must not reach RawPost.location, which is str.
                            c_city, c_lat, c_lon = city, lat, lon
                            if (hit := infer_city(comment["textDisplay"])):
                                c_city, c_lat, c_lon = hit

                            posts.append(
                                RawPost(
                                    platform="YouTube",
                                    author_handle=author,
                                    author_name=author,
                                    author_followers=0,  # YT API doesn't expose subscriber count for commenters
                                    author_verified=False,
                                    author_account_age_days=0,
                                    text=comment["textDisplay"],
                                    hashtags=[],
                                    engagement={
                                        "likes": comment.get("likeCount", 0),
                                        "replies": comment_item["snippet"]["totalReplyCount"],
                                    },
                                    url=f"{url}&lc={comment['parentId']}",
                                    created_at=datetime.fromisoformat(
                                        comment["publishedAt"].replace("Z", "+00:00")
                                    ).replace(tzinfo=None),
                                    location=c_city,
                                    latitude=c_lat,
                                    longitude=c_lon,
                                    metadata={
                                        "video_id": video_id,
                                        "channel_id": channel_id,
                                        "comment_id": comment["parentId"],
                                        "author_channel_id": author_channel_id,
                                        "is_comment": True,
                                    },
                                )
                            )

                    except Exception as exc:
                        # Comments disabled or other error
                        log.warning("Could not fetch comments for %s: %s", video_id, exc)

            except Exception as exc:
                log.warning("YouTube search for '%s' failed: %s", term, exc)
                continue

        return posts

    def _batch_stats(self, video_ids: list[str]) -> dict[str, dict]:
        """video_id -> statistics, in one call for the whole page."""
        if not video_ids or not self._afford(_COST_LIST):
            return {}
        try:
            resp = self.youtube.videos().list(
                id=",".join(video_ids[:50]), part="statistics",
            ).execute()
            return {i["id"]: i.get("statistics", {}) for i in resp.get("items", [])}
        except Exception as exc:
            log.warning("Could not fetch video stats: %s", exc)
            return {}

    def _batch_channels(self, channel_ids: set[str]) -> dict[str, tuple[str, int]]:
        """channel_id -> (title, subscriber_count), in one call."""
        ids = list(channel_ids)
        if not ids or not self._afford(_COST_LIST):
            return {}
        try:
            resp = self.youtube.channels().list(
                id=",".join(ids[:50]), part="snippet,statistics",
            ).execute()
            return {
                i["id"]: (
                    i.get("snippet", {}).get("title", ""),
                    int(i.get("statistics", {}).get("subscriberCount", 0)),
                )
                for i in resp.get("items", [])
            }
        except Exception as exc:
            log.warning("Could not fetch channel info: %s", exc)
            return {}

    async def lookup_channel(self, channel_handle: str) -> dict:
        """OSINT: Look up a YouTube channel by handle.

        Returns channel metadata: subscriber count, video count, description, etc.
        """
        if not self.youtube:
            return {"error": "YouTube API not configured"}

        # Analyst-triggered, so it is charged to the ledger for honest accounting
        # but never refused — a lookup an investigator asked for outranks the
        # background sweep, which backs off on its own once the budget is thin.
        self._roll_day()
        self._spent += _COST_SEARCH + _COST_LIST

        try:
            # Search for channel
            search_response = self.youtube.search().list(
                q=channel_handle, part="snippet", type="channel", maxResults=1
            ).execute()

            items = search_response.get("items", [])
            if not items:
                return {"error": f"Channel '{channel_handle}' not found"}

            channel_id = items[0]["id"]["channelId"]

            # Fetch full channel details
            channel_response = self.youtube.channels().list(
                id=channel_id,
                part="snippet,statistics,brandingSettings,contentDetails",
            ).execute()

            channel = channel_response.get("items", [{}])[0]
            snippet = channel.get("snippet", {})
            stats = channel.get("statistics", {})
            branding = channel.get("brandingSettings", {})

            return {
                "channel_id": channel_id,
                "name": snippet.get("title", ""),
                "handle": snippet.get("customUrl", channel_handle),
                "description": snippet.get("description", ""),
                "url": f"https://www.youtube.com/channel/{channel_id}",
                "subscribers": int(stats.get("subscriberCount", 0)),
                "videos": int(stats.get("videoCount", 0)),
                "views": int(stats.get("viewCount", 0)),
                "profile_image": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "keywords": branding.get("keywords", ""),
                "country": branding.get("channel", {}).get("country", ""),
            }
        except Exception as exc:
            log.warning("YouTube channel lookup for '%s' failed: %s", channel_handle, exc)
            return {"error": str(exc)}
