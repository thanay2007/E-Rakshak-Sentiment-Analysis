"""YouTube Data API v3 adapter — video search, comments, and channel OSINT.

Activates when YOUTUBE_API_KEY is set in .env. Searches for videos matching
watch terms and extracts comments for sentiment analysis and OSINT.

Rate limits: 10,000 quota units per day (shared quota for all operations).
  - video search: ~100 units per query
  - comments fetch: ~1 unit per comment
  - channel info: ~2 units per channel
"""
import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.crawlers.base import Collector
from app.ml.geo import infer_city
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")


class YouTubeCollector(Collector):
    name = "YouTube"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self.youtube = None
        self._load_client()

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

        posts: list[RawPost] = []
        # Search for recent videos (published in last 7 days)
        search_after = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        for term in watch_terms:
            try:
                # Search for videos
                search_response = self.youtube.search().list(
                    q=term,
                    part="snippet",
                    type="video",
                    maxResults=10,
                    order="relevance",
                    publishedAfter=search_after,
                    relevanceLanguage="en,hi,gu",
                    regionCode="IN",
                ).execute()

                for item in search_response.get("items", []):
                    video_id = item["id"]["videoId"]
                    snippet = item["snippet"]

                    # Fetch video details (statistics, view count)
                    try:
                        video_details = self.youtube.videos().list(
                            id=video_id,
                            part="statistics,contentDetails",
                        ).execute()
                        stats = video_details.get("items", [{}])[0].get("statistics", {})
                        view_count = int(stats.get("viewCount", 0))
                        like_count = int(stats.get("likeCount", 0))
                        comment_count = int(stats.get("commentCount", 0))
                    except Exception as exc:
                        log.warning("Could not fetch video stats for %s: %s", video_id, exc)
                        view_count = like_count = comment_count = 0

                    # Fetch channel info
                    channel_id = snippet["channelId"]
                    try:
                        channel_info = self.youtube.channels().list(
                            id=channel_id, part="snippet,statistics"
                        ).execute()
                        channel_data = channel_info.get("items", [{}])[0]
                        channel_name = channel_data.get("snippet", {}).get("title", "")
                        channel_subs = int(
                            channel_data.get("statistics", {}).get("subscriberCount", 0)
                        )
                    except Exception as exc:
                        log.warning("Could not fetch channel info for %s: %s", channel_id, exc)
                        channel_name = ""
                        channel_subs = 0

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
                            metadata={"video_id": video_id, "channel_id": channel_id},
                        )
                    )

                    # Fetch and process comments
                    try:
                        comments_response = self.youtube.commentThreads().list(
                            videoId=video_id,
                            part="snippet",
                            maxResults=20,
                            order="relevance",
                            searchTerms=term,
                            textFormat="plainText",
                        ).execute()

                        for comment_item in comments_response.get("items", []):
                            comment = comment_item["snippet"]["topLevelComment"]["snippet"]
                            author = comment["authorDisplayName"]
                            author_url = comment.get("authorChannelUrl", "")
                            author_channel_id = (
                                comment.get("authorChannelId", {}).get("value", "")
                            )

                            # Extract location if possible from comment text
                            location = infer_city(comment["textDisplay"])

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
                                    location=location,
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

    async def lookup_channel(self, channel_handle: str) -> dict:
        """OSINT: Look up a YouTube channel by handle.

        Returns channel metadata: subscriber count, video count, description, etc.
        """
        if not self.youtube:
            return {"error": "YouTube API not configured"}

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
