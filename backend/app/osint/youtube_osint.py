"""YouTube-specific OSINT functions — channel tracking, user enumeration, etc.

Requires YOUTUBE_API_KEY to be set in .env. Provides:
  • Channel metadata extraction
  • Video playlist enumeration
  • Comment analysis by author
  • Upload pattern analysis (frequency, timing)
  • Cross-platform handle correlation
"""
import logging
from datetime import datetime, timezone

from app.config import settings

log = logging.getLogger("sentinel.osint")


def _get_youtube_client():
    """Lazy-load YouTube API client."""
    try:
        from googleapiclient.discovery import build
        if not settings.YOUTUBE_API_KEY:
            return None
        return build("youtube", "v3", developerKey=settings.YOUTUBE_API_KEY)
    except Exception as exc:
        log.warning("YouTube API client unavailable: %s", exc)
        return None


async def profile_channel(channel_id: str) -> dict:
    """Extract comprehensive profile data from a YouTube channel.

    Includes: metadata, recent uploads, activity patterns, playlists.
    """
    youtube = _get_youtube_client()
    if not youtube:
        return {"error": "YouTube API not configured"}

    try:
        # Get channel info
        channel_response = youtube.channels().list(
            id=channel_id,
            part="snippet,statistics,brandingSettings,topicDetails,contentDetails",
        ).execute()

        if not channel_response.get("items"):
            return {"error": f"Channel {channel_id} not found"}

        channel = channel_response["items"][0]
        snippet = channel.get("snippet", {})
        stats = channel.get("statistics", {})
        topics = channel.get("topicDetails", {})
        content = channel.get("contentDetails", {})

        # Get uploads playlist ID
        uploads_id = content.get("relatedPlaylists", {}).get("uploads", "")

        # Fetch recent videos
        recent_videos = []
        if uploads_id:
            try:
                videos_response = youtube.playlistItems().list(
                    playlistId=uploads_id,
                    part="snippet",
                    maxResults=10,
                ).execute()

                for item in videos_response.get("items", []):
                    v_snippet = item["snippet"]
                    recent_videos.append({
                        "video_id": v_snippet["resourceId"]["videoId"],
                        "title": v_snippet["title"],
                        "published": v_snippet["publishedAt"],
                        "description": v_snippet["description"][:200],
                    })
            except Exception as exc:
                log.warning("Could not fetch uploads for %s: %s", channel_id, exc)

        return {
            "channel_id": channel_id,
            "url": f"https://www.youtube.com/channel/{channel_id}",
            "name": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "profile_image": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "view_count": int(stats.get("viewCount", 0)),
            "join_date": snippet.get("publishedAt", ""),
            "country": snippet.get("country", ""),
            "custom_url": snippet.get("customUrl", ""),
            "keywords": channel.get("brandingSettings", {}).get("keywords", ""),
            "topic_ids": topics.get("topicIds", []),
            "recent_videos": recent_videos,
        }

    except Exception as exc:
        log.warning("Channel profile fetch failed for %s: %s", channel_id, exc)
        return {"error": str(exc)}


async def analyze_video_comments(video_id: str, top_n: int = 50) -> dict:
    """Analyze comments on a video — aggregate sentiment, identify key users.

    Returns: comment statistics, top commenters, discussion themes.
    """
    youtube = _get_youtube_client()
    if not youtube:
        return {"error": "YouTube API not configured"}

    try:
        comments_response = youtube.commentThreads().list(
            videoId=video_id,
            part="snippet",
            maxResults=top_n,
            order="relevance",
            textFormat="plainText",
        ).execute()

        comments = []
        top_commenters = {}

        for item in comments_response.get("items", []):
            comment = item["snippet"]["topLevelComment"]["snippet"]
            author = comment["authorDisplayName"]
            text = comment["textDisplay"]

            comments.append({
                "author": author,
                "text": text,
                "likes": comment.get("likeCount", 0),
                "published": comment["publishedAt"],
                "author_channel_id": comment.get("authorChannelId", {}).get("value", ""),
            })

            # Track top commenters
            if author not in top_commenters:
                top_commenters[author] = {"count": 0, "avg_likes": 0}
            top_commenters[author]["count"] += 1
            top_commenters[author]["avg_likes"] = (
                top_commenters[author]["avg_likes"] * (top_commenters[author]["count"] - 1)
                + comment.get("likeCount", 0)
            ) / top_commenters[author]["count"]

        # Sort commenters by engagement
        top_commenters = sorted(
            top_commenters.items(),
            key=lambda x: x[1]["count"] * x[1]["avg_likes"],
            reverse=True,
        )[:10]

        return {
            "video_id": video_id,
            "total_comments": len(comments),
            "top_commenters": [
                {"name": name, "comment_count": data["count"], "avg_likes": round(data["avg_likes"], 1)}
                for name, data in top_commenters
            ],
            "recent_comments": comments[:20],
        }

    except Exception as exc:
        log.warning("Comment analysis failed for %s: %s", video_id, exc)
        return {"error": str(exc)}


async def find_user_channels(display_name: str) -> dict:
    """Find YouTube channels associated with a display name.

    Does NOT work with display names that aren't used in uploads.
    Better approach: search comments/videos and extract channel IDs.
    """
    youtube = _get_youtube_client()
    if not youtube:
        return {"error": "YouTube API not configured"}

    try:
        search_response = youtube.search().list(
            q=display_name,
            part="snippet",
            type="channel",
            maxResults=5,
        ).execute()

        channels = []
        for item in search_response.get("items", []):
            channel_id = item["id"]["channelId"]
            channels.append({
                "channel_id": channel_id,
                "name": item["snippet"]["title"],
                "url": f"https://www.youtube.com/channel/{channel_id}",
                "thumbnail": item["snippet"].get("thumbnails", {}).get("high", {}).get("url", ""),
            })

        return {
            "query": display_name,
            "results": channels,
        }

    except Exception as exc:
        log.warning("User channel search failed for '%s': %s", display_name, exc)
        return {"error": str(exc)}


async def extract_channel_from_comment_author(comment_text: str, video_id: str) -> dict:
    """Find channel ID from a comment author on a specific video.

    YouTube API returns author_channel_id in comment threads.
    Use this to track user activity across videos.
    """
    youtube = _get_youtube_client()
    if not youtube:
        return {"error": "YouTube API not configured"}

    try:
        # Search for comment with exact text
        comments_response = youtube.commentThreads().list(
            videoId=video_id,
            part="snippet",
            searchTerms=comment_text[:100],  # First 100 chars for search
            textFormat="plainText",
            maxResults=20,
        ).execute()

        results = []
        for item in comments_response.get("items", []):
            comment = item["snippet"]["topLevelComment"]["snippet"]
            if comment["textDisplay"].lower().startswith(comment_text.lower()[:50]):
                results.append({
                    "author": comment["authorDisplayName"],
                    "channel_id": comment.get("authorChannelId", {}).get("value", ""),
                    "profile_url": comment.get("authorProfileImageUrl", ""),
                })

        return {"video_id": video_id, "authors": results}

    except Exception as exc:
        log.warning("Comment author extraction failed: %s", exc)
        return {"error": str(exc)}


async def video_engagement_analysis(video_id: str) -> dict:
    """Analyze video engagement metrics — views, likes, comments trend.

    Returns engagement ratio and audience sentiment proxies.
    """
    youtube = _get_youtube_client()
    if not youtube:
        return {"error": "YouTube API not configured"}

    try:
        # Get video stats
        video_response = youtube.videos().list(
            id=video_id,
            part="snippet,statistics",
        ).execute()

        if not video_response.get("items"):
            return {"error": f"Video {video_id} not found"}

        video = video_response["items"][0]
        snippet = video["snippet"]
        stats = video["statistics"]

        views = int(stats.get("viewCount", 0))
        likes = int(stats.get("likeCount", 0))
        comments = int(stats.get("commentCount", 0))

        # Calculate engagement ratios
        like_ratio = (likes / views * 100) if views > 0 else 0
        comment_ratio = (comments / views * 100) if views > 0 else 0
        comment_like_ratio = (comments / likes) if likes > 0 else 0

        return {
            "video_id": video_id,
            "title": snippet["title"],
            "published": snippet["publishedAt"],
            "views": views,
            "likes": likes,
            "comments": comments,
            "engagement_metrics": {
                "like_ratio_percent": round(like_ratio, 2),
                "comment_ratio_percent": round(comment_ratio, 2),
                "comments_per_like": round(comment_like_ratio, 2),
            },
            "sentiment_proxy": "positive" if like_ratio > 3 else "neutral" if like_ratio > 1 else "negative",
        }

    except Exception as exc:
        log.warning("Engagement analysis failed for %s: %s", video_id, exc)
        return {"error": str(exc)}
