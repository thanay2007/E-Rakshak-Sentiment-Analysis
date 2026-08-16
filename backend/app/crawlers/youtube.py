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
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.crawlers.base import Collector
from app.ml.geo import dominant_city, infer_city
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

# Documented quota costs (units) for the calls this adapter makes.
_COST_SEARCH = 100
_COST_LIST = 1        # videos.list / channels.list / commentThreads.list

# YouTube resets project quota at midnight Pacific, not UTC.
_QUOTA_TZ = ZoneInfo("America/Los_Angeles")

# Rotated across cycles, one per search call. `relevanceLanguage` takes a single
# ISO-639-1 code — a list is a hard 400 — and it *biases* ranking rather than
# filtering, so highly relevant results in other languages still come back.
# Rotating covers the languages these cities actually post in (English, Hindi,
# Gujarati, and the romanized Hinglish/Gujlish that ride on the first) without
# any of the three crowding out the others.
_RELEVANCE_LANGUAGES = ("en", "hi", "gu")


def _norm(s: str) -> str:
    """Lowercase + NFC, so Indic text typed on two keyboards still matches
    (the same reason app/ml/geo.py normalises before it looks for a city)."""
    return unicodedata.normalize("NFC", s or "").lower()


def _mentions(term: str, blob: str) -> bool:
    """Does `blob` actually contain the searched term?

    Multi-word terms are matched word by word rather than as a phrase: YouTube
    ranks "rasta roko" against a title that says "roko" in one line and "rasta"
    in another, and that is a genuine match. Words shorter than four characters
    are ignored on their own — "ho", "jam" and "an" hit everything.
    """
    needle = _norm(term).strip()
    if not needle:
        return False
    if needle in blob:
        return True
    words = [w for w in re.split(r"\s+", needle) if len(w) >= 4]
    return bool(words) and all(w in blob for w in words)


def _is_relevant(term: str, blob: str) -> bool:
    """Is this search result actually about the thing that was searched for?

    Deliberately a *relevance* test and never a language one. This console's
    rule is that nothing is dropped for the script it is written in — that is
    an evasion route, and a Gujarati or Urdu post about Surat has to reach an
    officer exactly like an English one does. What is dropped here is a video
    that has nothing to do with the query or the city, in any language.

    The gap this closes is real and was measured on the live corpus: 51 Chinese
    and Korean short-drama videos were stored as posts from Surat, because the
    search term was pushed into the query, YouTube ranked whatever it liked,
    and the adapter then stamped the city onto every result it got back. They
    are not quiet noise — they inflate Surat's volume on the district heatmap
    and are sentiment-scored as if a resident wrote them.

    The channel's country was tried as a third signal and dropped: measured
    over four live queries, `country == IN` was true of nearly every result
    including the recipe videos and the cartoons, so it separates nothing.
    """
    return _mentions(term, blob) or bool(infer_city(blob))


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
        searches = 0
        dropped = 0
        # Search for recent videos (published in last 7 days)
        search_after = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        for term, city in self._next_targets(watch_terms):
            if not self._afford(_COST_SEARCH):
                log.info("YouTube daily quota budget spent (%d units) — pausing until reset",
                         self._spent)
                break
            query = term if infer_city(term) else f"{term} {city}"
            # No coordinates are taken from the query any more: the city a
            # result is filed under now comes from the result's own text.
            # One code per call, rotated per search, so a cycle covers all three
            # rather than three cycles each covering one.
            language = _RELEVANCE_LANGUAGES[searches % len(_RELEVANCE_LANGUAGES)]
            searches += 1
            try:
                # Search for videos
                search_response = self.youtube.search().list(
                    q=query,
                    part="snippet",
                    type="video",
                    maxResults=10,
                    order="relevance",
                    publishedAfter=search_after,
                    relevanceLanguage=language,
                    regionCode="IN",
                ).execute()

                items = search_response.get("items", [])
                # videos.list and channels.list both accept up to 50 comma-joined
                # ids for the same 1 unit, so fetch the whole result page at once
                # rather than paying per video.
                videos = self._batch_videos(
                    [i["id"]["videoId"] for i in items]
                )
                channels = self._batch_channels(
                    {i["snippet"]["channelId"] for i in items}
                )

                for item in items:
                    video_id = item["id"]["videoId"]
                    snippet = item["snippet"]

                    video = videos.get(video_id, {})
                    stats = video.get("statistics", {})
                    view_count = int(stats.get("viewCount", 0))
                    like_count = int(stats.get("likeCount", 0))
                    comment_count = int(stats.get("commentCount", 0))

                    channel_id = snippet["channelId"]
                    channel_name, channel_subs = channels.get(channel_id, ("", 0))

                    # The *full* snippet, not the search result's: search
                    # truncates the description to about 160 characters and
                    # carries no tags at all, and both are where a video says
                    # which city it is about. Same 1 quota unit either way.
                    full = video.get("snippet", snippet)
                    blob = _norm(" ".join((
                        full.get("title", "") or snippet.get("title", ""),
                        full.get("description", "") or snippet.get("description", ""),
                        " ".join(full.get("tags", []) or []),
                        snippet.get("channelTitle", ""), channel_name)))
                    if not _is_relevant(term, blob):
                        # Nothing ties it to the query or to any city we watch,
                        # so it is not a post from here — and neither are its
                        # comments, which is why this drops the whole video.
                        dropped += 1
                        continue

                    # Geography from the text, not from the query. Searching
                    # "बच्चा चोर Ahmedabad" returns child-lifting news from
                    # Moradabad and Begusarai; stamping those Ahmedabad is what
                    # put other states' incidents on Gujarat's heatmap. When
                    # the video names no city we watch, its location is left
                    # empty — unknown, rather than wrong.
                    hit = dominant_city(blob)
                    v_city, v_lat, v_lon = hit if hit else ("", 0.0, 0.0)

                    # Create a post for the video itself
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    created = datetime.fromisoformat(
                        snippet["publishedAt"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)

                    posts.append(
                        RawPost(
                            platform="YouTube",
                            author_handle=snippet["channelTitle"],
                            # The channel id, which survives a rename — the
                            # field RawPost actually keeps. The `metadata=` this
                            # adapter used to pass was silently dropped by the
                            # model (it declares no such field), so the video
                            # and channel ids never reached the database at all.
                            author_id=channel_id,
                            author_name=channel_name or snippet["channelTitle"],
                            author_followers=channel_subs,
                            author_verified=False,
                            author_account_age_days=0,
                            # The full description, not the search result's
                            # ~160-character truncation — the sentiment models
                            # score this text, and half a sentence is not what
                            # the channel published.
                            text=(full.get("title", "") or snippet["title"]) + "\n\n"
                                 + (full.get("description", "") or snippet["description"]),
                            hashtags=[],
                            engagement={
                                "likes": like_count,
                                "views": view_count,
                                "comments": comment_count,
                            },
                            url=url,
                            created_at=created,
                            location=v_city,
                            latitude=v_lat,
                            longitude=v_lon,
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
                            # The thread id, which is also the top-level
                            # comment's id. `snippet.parentId` exists only on
                            # *replies* — reading it here raised KeyError on
                            # every single video, and the except below logged
                            # that as "comments disabled", so this adapter has
                            # never collected a YouTube comment at all. On a
                            # municipal page the caption is a press release and
                            # the grievance is thirty comments down, so this one
                            # key was costing the console the better half of the
                            # platform.
                            thread_id = comment_item["id"]
                            comment = comment_item["snippet"]["topLevelComment"]["snippet"]
                            author = comment["authorDisplayName"]
                            author_channel_id = (
                                comment.get("authorChannelId", {}).get("value", "")
                            )

                            # A comment inherits the city resolved for its video
                            # — which may be none — and if its own text names a
                            # city, that wins. infer_city returns (city, lat,
                            # lon) or None; the tuple must not reach
                            # RawPost.location, which is a str.
                            c_city, c_lat, c_lon = v_city, v_lat, v_lon
                            if (where := infer_city(comment["textDisplay"])):
                                c_city, c_lat, c_lon = where

                            posts.append(
                                RawPost(
                                    platform="YouTube",
                                    author_handle=author,
                                    # The commenter's own channel id — the one
                                    # thing that still identifies them after a
                                    # display-name change.
                                    author_id=author_channel_id,
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
                                    url=f"{url}&lc={thread_id}",
                                    created_at=datetime.fromisoformat(
                                        comment["publishedAt"].replace("Z", "+00:00")
                                    ).replace(tzinfo=None),
                                    location=c_city,
                                    latitude=c_lat,
                                    longitude=c_lon,
                                )
                            )

                    except Exception as exc:
                        # Comments disabled or other error
                        log.warning("Could not fetch comments for %s: %s", video_id, exc)

            except Exception as exc:
                log.warning("YouTube search for '%s' failed: %s", term, exc)
                continue

        if dropped:
            log.info("YouTube: dropped %d search results unrelated to the query "
                     "or the city (kept %d posts)", dropped, len(posts))
        return posts

    def _batch_videos(self, video_ids: list[str]) -> dict[str, dict]:
        """video_id -> {"snippet", "statistics"}, in one call for the whole page.

        `snippet` rides along for free — videos.list costs one unit however many
        parts are asked for — and it is what makes the relevance test work: the
        search result's description is truncated at ~160 characters and carries
        no tags, which is where a video usually says which city it is about.
        """
        if not video_ids or not self._afford(_COST_LIST):
            return {}
        try:
            resp = self.youtube.videos().list(
                id=",".join(video_ids[:50]), part="snippet,statistics",
            ).execute()
            return {i["id"]: i for i in resp.get("items", [])}
        except Exception as exc:
            log.warning("Could not fetch video details: %s", exc)
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
