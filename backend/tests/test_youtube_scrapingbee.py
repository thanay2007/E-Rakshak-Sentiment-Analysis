# -*- coding: utf-8 -*-
"""The ScrapingBee YouTube adapter, against canned responses — no network.

ScrapingBee documents its search response two ways (YouTube's own renderer
objects under ``results``, and plain ``title``/``link`` pairs under
``videos``); both must parse. Relevance and geography must behave exactly as
in the Data API adapter, and spending must stop at the daily credit budget.
"""
import asyncio
from datetime import datetime

import httpx
import pytest

from app.config import settings
from app.crawlers import youtube_scrapingbee as sb

RENDERER_RESULT = {
    "videoId": "abcdefghijk",
    "title": {"runs": [{"text": "Surat flood: roads under water"}]},
    "longBylineText": {"runs": [{"text": "Gujarat News",
                                 "navigationEndpoint": {"browseEndpoint":
                                                        {"browseId": "UC123"}}}]},
    "shortViewCountText": {"simpleText": "1.2K views"},
    "publishedTimeText": {"simpleText": "2 days ago"},
}
PLAIN_RESULT = {"title": "Rajkot traffic jam today",
                "link": "https://www.youtube.com/watch?v=ZYXWVUTSRQP"}
OFF_TOPIC = {"videoId": "00000000000",
             "title": {"runs": [{"text": "Best pasta recipe"}]}}


def test_renderer_fields_parse():
    assert sb._video_id(RENDERER_RESULT) == "abcdefghijk"
    assert sb._channel(RENDERER_RESULT) == ("UC123", "Gujarat News")
    assert sb._count(RENDERER_RESULT["shortViewCountText"]) == 1200
    assert sb._text(RENDERER_RESULT["title"]) == "Surat flood: roads under water"


def test_plain_link_results_parse():
    assert sb._video_id(PLAIN_RESULT) == "ZYXWVUTSRQP"
    assert sb._video_id({"link": "https://youtu.be/ZYXWVUTSRQP"}) == "ZYXWVUTSRQP"
    assert sb._video_id({"link": "https://www.youtube.com/shorts/ZYXWVUTSRQP"}) == "ZYXWVUTSRQP"


@pytest.mark.parametrize("raw,expected", [
    ("12,345 views", 12345), ("3.4M views", 3_400_000), ("2 lakh views", 200_000),
    (987, 987), ("", 0), (None, 0),
])
def test_counts(raw, expected):
    assert sb._count(raw) == expected


def test_dates():
    now = datetime(2026, 10, 8, 12, 0, 0)
    assert sb._when("2 days ago", now) == datetime(2026, 10, 6, 12, 0, 0)
    assert sb._when("Streamed 3 hours ago", now) == datetime(2026, 10, 8, 9, 0, 0)
    assert sb._when("2023-01-01") == datetime(2023, 1, 1)
    assert sb._when("20230101") == datetime(2023, 1, 1)
    assert sb._when("2023-01-01T10:00:00Z") == datetime(2023, 1, 1, 10, 0, 0)
    assert sb._when("yesterday-ish") is None


def _collector(monkeypatch, responses, *, budget=1000, youtube=None):
    """A collector whose ScrapingBee calls are served from `responses` and
    whose free YouTube web calls are served from `youtube` (404 by default:
    watch page unreadable, so paid metadata is the fallback)."""
    monkeypatch.setattr(settings, "SCRAPINGBEE_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SCRAPINGBEE_DAILY_CREDITS", budget)
    monkeypatch.setattr(settings, "YOUTUBE_TERMS_PER_CYCLE", 1)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.youtube.com":
            # The key must never travel to YouTube.
            assert "Authorization" not in request.headers
            return (youtube or (lambda r: httpx.Response(404)))(request)
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-key"
        assert "api_key" not in str(request.url)   # never in the query string
        return responses(request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(sb.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return sb.ScrapingBeeYouTubeCollector(), calls


def test_collect_keeps_relevant_drops_off_topic(monkeypatch):
    def responses(request):
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [RENDERER_RESULT, OFF_TOPIC]})
        if request.url.params["video_id"] != "abcdefghijk":
            return httpx.Response(200, json={"title": "Best pasta recipe",
                                             "description": "Cook at home."})
        return httpx.Response(200, json={
            "video_id": "abcdefghijk", "title": "Surat flood: roads under water",
            "description": "Heavy rain in Surat. #suratrain",
            "channel_id": "UC123", "channel_title": "Gujarat News",
            "view_count": 5000, "like_count": 300, "comment_count": 12,
            "upload_date": "2026-10-06"})

    collector, _ = _collector(monkeypatch, responses)
    posts = asyncio.run(collector.collect(["flood"]))
    assert [p.url for p in posts] == ["https://www.youtube.com/watch?v=abcdefghijk"]
    post = posts[0]
    assert post.location == "Surat"
    assert post.engagement == {"likes": 300, "views": 5000, "comments": 12}
    assert post.author_id == "UC123"
    assert "suratrain" in post.hashtags
    # Seen once, never paid for again.
    assert asyncio.run(collector.collect(["flood"])) == []


def test_plain_videos_shape(monkeypatch):
    def responses(request):
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"videos": [PLAIN_RESULT]})
        return httpx.Response(500)   # details unavailable: title alone must do

    collector, _ = _collector(monkeypatch, responses)
    posts = asyncio.run(collector.collect(["traffic"]))
    assert len(posts) == 1 and posts[0].location == "Rajkot"


def test_budget_stops_spending(monkeypatch):
    collector, calls = _collector(
        monkeypatch, lambda r: httpx.Response(200, json={"results": []}), budget=4)
    assert asyncio.run(collector.collect(["flood"])) == []
    assert calls == []   # a 5-credit search does not fit a 4-credit budget


def test_refused_key_goes_offline(monkeypatch):
    collector, _ = _collector(monkeypatch, lambda r: httpx.Response(401))
    assert collector.is_configured()
    assert asyncio.run(collector.collect(["flood"])) == []
    assert not collector.is_configured()
    assert "refused" in collector.status_detail()


def test_free_watch_page_and_comments_save_credits(monkeypatch):
    """With the watch page readable, no metadata is bought and the comment
    threads come along with the video."""
    from test_youtube_web import COMMENTS_PAGE, WATCH_PAGE

    def youtube(request):
        body = request.read().decode()
        return httpx.Response(200, json=COMMENTS_PAGE if "continuation" in body else WATCH_PAGE)

    def responses(request):
        assert request.url.path.endswith("/search"), "metadata must not be bought"
        return httpx.Response(200, json={"results": [RENDERER_RESULT]})

    collector, calls = _collector(monkeypatch, responses, youtube=youtube)
    posts = asyncio.run(collector.collect(["flood"]))
    assert len(calls) == 1 and collector.credit_status()["spent"] == 5
    video, *comments = posts
    assert video.engagement["likes"] == 75 and video.author_verified
    assert [c.text for c in comments] == ["Roads in Adajan are flooded", "Same in Vesu"]
    assert comments[0].url == "https://www.youtube.com/watch?v=abcdefghijk&lc=Ugw1"
