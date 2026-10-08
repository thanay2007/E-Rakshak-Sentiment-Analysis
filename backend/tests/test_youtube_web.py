# -*- coding: utf-8 -*-
"""YouTube's keyless web routes, against canned payloads — no network.

The payloads are trimmed copies of live innertube responses (October 2026):
the watch page (``next`` with a videoId), a comments page in the current
``commentEntityPayload`` shape, a replies page, and a channel's Videos tab in
the ``lockupViewModel`` shape. The older ``commentRenderer`` shape must parse
too, because YouTube has served both within the last two years.
"""
import asyncio
import json
from datetime import datetime

import httpx
import pytest

from app.config import settings
from app.crawlers import youtube_web as yw

WATCH_PAGE = {"contents": {"twoColumnWatchNextResults": {"results": {"results": {"contents": [
    {"videoPrimaryInfoRenderer": {
        "title": {"runs": [{"text": "Surat flood: roads under water"}]},
        "viewCount": {"videoViewCountRenderer": {"viewCount": {"simpleText": "19,468 views"}}},
        "dateText": {"simpleText": "Oct 5, 2026"},
        "videoActions": {"menuRenderer": {"topLevelButtons": [{"segmentedLikeDislikeButtonViewModel": {
            "likeButtonViewModel": {"accessibilityText":
                                    "like this video along with 74 other people"}}}]}}}},
    {"videoSecondaryInfoRenderer": {
        "owner": {"videoOwnerRenderer": {
            "title": {"runs": [{"text": "Gujarat News", "navigationEndpoint": {
                "browseEndpoint": {"browseId": "UC123"}}}]},
            "subscriberCountText": {"simpleText": "27.5M subscribers"},
            "badges": [{"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_VERIFIED"}}]}},
        "attributedDescription": {"content": "Heavy rain in Surat. #suratrain"}}},
    {"itemSectionRenderer": {"sectionIdentifier": "comment-item-section", "contents": [
        {"continuationItemRenderer": {"continuationEndpoint": {
            "continuationCommand": {"token": "COMMENTS-TOKEN"}}}}]}},
]}}}}}


def _entity(cid, text, author, likes="0", replies="", level=0):
    return {"payload": {"commentEntityPayload": {
        "properties": {"commentId": cid, "content": {"content": text},
                       "publishedTime": "2 days ago", "replyLevel": level},
        "author": {"channelId": f"UC-{author}", "displayName": f"@{author}",
                   "isVerified": False},
        "toolbar": {"likeCountNotliked": likes, "replyCount": replies}}}}


COMMENTS_PAGE = {
    "onResponseReceivedEndpoints": [{"reloadContinuationItemsCommand": {"continuationItems": [
        {"commentsHeaderRenderer": {"countText": {"runs": [{"text": "1,204"},
                                                           {"text": " Comments"}]}}},
        {"commentThreadRenderer": {
            "commentViewModel": {"commentViewModel": {"commentId": "Ugw1"}},
            "replies": {"commentRepliesRenderer": {"contents": [{"continuationItemRenderer": {
                "continuationEndpoint": {"continuationCommand": {"token": "REPLIES-TOKEN"}}}}]}}}},
        {"commentThreadRenderer": {
            "commentViewModel": {"commentViewModel": {"commentId": "Ugw2"}}}},
    ]}}],
    "frameworkUpdates": {"entityBatchUpdate": {"mutations": [
        _entity("Ugw1", "Roads in Adajan are flooded", "resident", likes="1.2K", replies="2"),
        _entity("Ugw2", "Same in Vesu", "neighbour", likes="3"),
    ]}},
}

REPLIES_PAGE = {"frameworkUpdates": {"entityBatchUpdate": {"mutations": [
    _entity("Ugw1.r1", "Municipality has not come yet", "local", level=1),
]}}}

OLD_SHAPE = {"contents": [{"commentThreadRenderer": {"comment": {"commentRenderer": {
    "commentId": "UgxOLD", "contentText": {"runs": [{"text": "Old style comment"}]},
    "authorText": {"simpleText": "@oldtimer"},
    "authorEndpoint": {"browseEndpoint": {"browseId": "UC-old"}},
    "voteCount": {"simpleText": "12"}, "replyCount": 0,
    "publishedTimeText": {"runs": [{"text": "1 day ago"}]}}}}}]}

CHANNEL_TAB = {
    "metadata": {"channelMetadataRenderer": {"title": "Gujarat News", "externalId": "UC123"}},
    "contents": [{"lockupViewModel": {
        "contentId": "ZYXWVUTSRQP", "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
        "metadata": {"lockupMetadataViewModel": {
            "title": {"content": "Rajkot traffic update"},
            "metadata": {"contentMetadataViewModel": {"metadataRows": [{"metadataParts": [
                {"text": {"content": "546 views"}},
                {"text": {"content": "23 minutes ago"}}]}]}}}}}}],
}

SEARCH_PAGE = {"contents": [
    {"videoRenderer": {"videoId": "abcdefghijk",
                       "title": {"runs": [{"text": "Surat flood: roads under water"}]},
                       "publishedTimeText": {"simpleText": "2 days ago"}}},
    {"videoRenderer": {"videoId": "00000000000",
                       "title": {"runs": [{"text": "Best pasta recipe"}]}}},
]}

PASTA_PAGE = {"contents": [{"videoPrimaryInfoRenderer": {
    "title": {"runs": [{"text": "Best pasta recipe"}]}}},
    {"videoSecondaryInfoRenderer": {"attributedDescription": {"content": "Cook at home."}}}]}


def _router(routes):
    """innertube calls → payloads, keyed by endpoint and a marker in the body."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read() or b"{}")
        endpoint = request.url.path.rsplit("/v1/", 1)[-1]
        seen.append((endpoint, body))
        key = body.get("continuation") or body.get("videoId") or body.get("browseId") \
            or body.get("url") or body.get("query")
        reply = routes.get((endpoint, key), routes.get(endpoint))
        if reply is None:
            return httpx.Response(404)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)
    return handler, seen


def _client(routes):
    handler, seen = _router(routes)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def test_watch_page_parses():
    client, seen = _client({"next": WATCH_PAGE})
    video = asyncio.run(yw.WebClient(client).video("abcdefghijk"))
    assert seen[0] == ("next", {"context": yw.CONTEXT, "videoId": "abcdefghijk"})
    assert video["title"] == "Surat flood: roads under water"
    assert video["description"].startswith("Heavy rain in Surat")
    assert (video["channel_id"], video["channel_name"]) == ("UC123", "Gujarat News")
    assert video["subscribers"] == 27_500_000 and video["verified"]
    assert (video["views"], video["likes"]) == (19_468, 75)
    assert video["published"] == datetime(2026, 10, 5)
    assert video["comments_token"] == "COMMENTS-TOKEN"


def test_comment_pages_parse_both_shapes():
    new = yw._parse_comments(COMMENTS_PAGE)
    assert [c["id"] for c in new] == ["Ugw1", "Ugw2"]
    assert new[0]["likes"] == 1200 and new[0]["replies"] == 2
    assert new[0]["reply_token"] == "REPLIES-TOKEN" and new[1]["reply_token"] == ""
    assert new[0]["author"] == "@resident" and new[0]["author_id"] == "UC-resident"
    old = yw._parse_comments(OLD_SHAPE)
    assert old[0]["text"] == "Old style comment" and old[0]["likes"] == 12
    assert old[0]["author_id"] == "UC-old"


def test_thread_posts_reads_comments_and_replies(monkeypatch):
    monkeypatch.setattr(settings, "YOUTUBE_REPLY_THREADS_PER_VIDEO", 3)
    client, _ = _client({("next", "COMMENTS-TOKEN"): COMMENTS_PAGE,
                         ("next", "REPLIES-TOKEN"): REPLIES_PAGE})
    video = yw.video_post("abcdefghijk", title="Surat flood", description="",
                          channel_id="UC123", channel_name="Gujarat News")
    seen: set[str] = set()
    posts = asyncio.run(yw.thread_posts(yw.WebClient(client), video, "COMMENTS-TOKEN", seen))
    assert [p.text for p in posts] == ["Roads in Adajan are flooded", "Same in Vesu",
                                       "Municipality has not come yet"]
    # The thread header's total, not the handful read.
    assert video.engagement["comments"] == 1204
    # A comment naming a city is filed there; the rest inherit the video's.
    assert posts[0].location == "Surat" and posts[1].location == "Surat"
    assert posts[2].url.endswith("&lc=Ugw1.r1")
    # Revisiting emits only what is new.
    assert asyncio.run(yw.thread_posts(yw.WebClient(client), video, "COMMENTS-TOKEN", seen)) == []


def test_channel_uploads(monkeypatch):
    client, seen = _client({
        ("navigation/resolve_url", "https://www.youtube.com/@gujaratnews"):
            {"endpoint": {"browseEndpoint": {"browseId": "UC123"}}},
        "browse": CHANNEL_TAB})
    channel = asyncio.run(yw.WebClient(client).channel("gujaratnews"))
    assert channel["id"] == "UC123" and channel["name"] == "Gujarat News"
    assert channel["uploads"][0]["video_id"] == "ZYXWVUTSRQP"
    assert channel["uploads"][0]["views"] == 546
    # An unknown handle is {}, not an error.
    assert asyncio.run(yw.WebClient(client).channel("@nobody")) == {}


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setattr(settings, "YOUTUBE_TERMS_PER_CYCLE", 1)
    monkeypatch.setattr(settings, "YOUTUBE_WATCHED_CHANNELS_PER_CYCLE", 0)
    monkeypatch.setattr(yw.YouTubeWebCollector, "_pause", staticmethod(_no_pause))
    c = yw.YouTubeWebCollector()
    c._cursor = 0
    return c


async def _no_pause():
    return None


def _serve(monkeypatch, routes):
    handler, seen = _router(routes)
    real = httpx.AsyncClient
    monkeypatch.setattr(yw.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler),
                                          **{k: v for k, v in kw.items() if k != "transport"}))
    return seen


def test_collect_keeps_relevant_with_comments(monkeypatch, collector):
    _serve(monkeypatch, {"search": SEARCH_PAGE,
                         ("next", "abcdefghijk"): WATCH_PAGE,
                         ("next", "00000000000"): PASTA_PAGE,
                         ("next", "COMMENTS-TOKEN"): COMMENTS_PAGE,
                         ("next", "REPLIES-TOKEN"): REPLIES_PAGE})
    posts = asyncio.run(collector.collect(["flood"]))
    urls = [p.url for p in posts]
    assert urls[0] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert not any("00000000000" in u for u in urls)   # off-topic video dropped
    assert len(posts) == 4                              # video + 2 comments + 1 reply
    assert posts[0].location == "Surat" and posts[0].author_followers == 27_500_000
    # Next cycle: the video is not read again, and the revisit finds nothing new.
    assert asyncio.run(collector.collect(["flood"])) == []


def test_watched_channel_uploads_are_read(monkeypatch, collector):
    monkeypatch.setattr(settings, "YOUTUBE_WATCHED_CHANNELS_PER_CYCLE", 2)
    monkeypatch.setattr(yw, "watched_accounts", lambda: ["gujaratnews", "not a handle!"])
    upload_page = json.loads(json.dumps(WATCH_PAGE).replace("Surat", "Rajkot"))
    _serve(monkeypatch, {
        ("navigation/resolve_url", "https://www.youtube.com/@gujaratnews"):
            {"endpoint": {"browseEndpoint": {"browseId": "UC123"}}},
        "browse": CHANNEL_TAB,
        ("next", "ZYXWVUTSRQP"): upload_page,
        "search": {"contents": []}})
    posts = asyncio.run(collector.collect(["flood"]))
    assert [p.url for p in posts] == ["https://www.youtube.com/watch?v=ZYXWVUTSRQP"]
    assert posts[0].location == "Rajkot"


def test_rate_limit_parks_the_route(monkeypatch, collector):
    _serve(monkeypatch, {"search": httpx.Response(429)})
    assert asyncio.run(collector.collect(["flood"])) == []
    assert not collector.is_configured()
    assert "429" in collector.status_detail()


def test_disabled_by_setting(monkeypatch, collector):
    monkeypatch.setattr(settings, "YOUTUBE_WEB_ENABLED", False)
    assert not collector.is_configured()


@pytest.mark.parametrize("raw,expected", [
    ("Oct 5, 2026", datetime(2026, 10, 5)),
    ("Premiered Oct 5, 2026", datetime(2026, 10, 5)),
    ("Streamed live on September 30, 2026", datetime(2026, 9, 30)),
])
def test_absolute_dates(raw, expected):
    assert yw._when(raw) == expected
