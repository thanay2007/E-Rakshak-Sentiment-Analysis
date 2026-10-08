# -*- coding: utf-8 -*-
"""The instagram-user-feed port, against canned responses — no network.

Pins the request recipe ported from pgrimaud/instagram-user-feed (endpoint,
app-id header, session cookie, query hashes), the way its responses are read,
and the collector's behaviour when Instagram refuses: keep what was read,
park the route, never prune an account for a fault of the route.
"""
import json

import pytest

from app.config import settings
from app.crawlers import instagram_userfeed as uf


def _node(code, caption, comments=0):
    return {"id": f"id-{code}", "shortcode": code, "taken_at_timestamp": 1_760_000_000,
            "edge_media_to_caption": {"edges": [{"node": {"text": caption}}]},
            "edge_liked_by": {"count": 40}, "edge_media_to_comment": {"count": comments},
            "display_url": f"https://cdn.example/{code}.jpg"}


def _profile(username, followers=5000, private=False, nodes=None):
    return {"data": {"user": {
        "id": "1234", "username": username, "full_name": "Surat City Police",
        "edge_followed_by": {"count": followers}, "is_verified": True,
        "is_private": private,
        "edge_owner_to_timeline_media": {
            "count": 2, "edges": [{"node": n} for n in (nodes or [])],
            "page_info": {"end_cursor": None}}}}}


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None, url="https://www.instagram.com/"):
        self.status_code = status
        self.text = text if text is not None else json.dumps(payload or {})
        self.url = url

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """Routes by URL; records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        self.headers = {}

    def get(self, url, params=None, headers=None, timeout=None):
        self.requests.append((url, params or {}, headers or {}))
        for marker, reply in self.routes.items():
            if marker in url + json.dumps(params or {}):
                return reply(params or {}) if callable(reply) else reply
        return FakeResponse(404)


def test_session_carries_the_cookie_and_library_headers():
    s = uf.make_session("abc")
    assert s.cookies.get("sessionid") == "abc"
    assert s.headers["x-requested-with"] == "XMLHttpRequest"
    assert "Chrome" in s.headers["user-agent"]


def test_profile_request_and_hydration():
    session = FakeSession({"web_profile_info": FakeResponse(
        payload=_profile("suratcitypolice", nodes=[_node("AAA", "Traffic alert #surat")]))})
    info = uf.profile_summary(uf.fetch_profile(session, "suratcitypolice"))
    url, params, headers = session.requests[0]
    assert url == "https://i.instagram.com/api/v1/users/web_profile_info/"
    assert params == {"username": "suratcitypolice"}
    assert headers == {"x-ig-app-id": uf.IG_APP_ID}
    assert info["followers"] == 5000 and info["verified"] and not info["private"]
    assert [n["shortcode"] for n in info["medias"]] == ["AAA"]


def test_comments_use_the_library_query_hash():
    payload = {"data": {"shortcode_media": {"edge_media_to_comment": {"edges": [
        {"node": {"id": "c1", "text": "Road is broken", "created_at": 1_760_000_100,
                  "owner": {"id": "9", "username": "resident"}}}]}}}}
    session = FakeSession({"graphql/query": FakeResponse(payload=payload)})
    nodes = uf.fetch_comments(session, "AAA", 5)
    _, params, _ = session.requests[0]
    assert params["query_hash"] == uf.QUERY_HASH_COMMENTS
    assert json.loads(params["variables"]) == {"shortcode": "AAA", "first": 5}
    assert nodes[0]["text"] == "Road is broken"


@pytest.mark.parametrize("response,error", [
    (FakeResponse(429), uf.RateLimited),
    (FakeResponse(200, text="<html>login</html>"), uf.RateLimited),
    (FakeResponse(400, text='{"message":"checkpoint_required"}'), uf.CheckpointRequired),
    (FakeResponse(200, payload={"data": {"user": None}}), uf.AccountUnavailable),
])
def test_refusals_are_typed(response, error):
    with pytest.raises(error):
        uf.fetch_profile(FakeSession({"web_profile_info": response}), "x")


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setattr(settings, "IG_SEED_USERNAMES_RAW", ["suratcitypolice:Surat"])
    monkeypatch.setattr(settings, "IG_SEEDS_PER_CYCLE", 8)
    monkeypatch.setattr(settings, "IG_WATCHED_ACCOUNTS_PER_CYCLE", 0)
    monkeypatch.setattr(settings, "IG_DISCOVERED_ACCOUNTS_PER_CYCLE", 0)
    monkeypatch.setattr(settings, "IG_HASHTAGS_PER_CYCLE", 0)
    monkeypatch.setattr(settings, "IG_COMMENTS_MAX_MEDIA_PER_CYCLE", 4)
    monkeypatch.setattr(uf.InstagramUserFeedCollector, "_pause", staticmethod(lambda: None))
    return uf.InstagramUserFeedCollector()


def test_collects_posts_and_comments(monkeypatch, collector):
    comments = {"data": {"shortcode_media": {"edge_media_to_comment": {"edges": [
        {"node": {"id": "c1", "text": "Still no water in Adajan",
                  "owner": {"id": "9", "username": "resident"}}}]}}}}
    session = FakeSession({
        "web_profile_info": FakeResponse(payload=_profile(
            "suratcitypolice", nodes=[_node("AAA", "Water cut notice", comments=3),
                                      _node("BBB", "", comments=0)])),
        "graphql/query": FakeResponse(payload=comments),
    })
    monkeypatch.setattr(uf, "make_session", lambda sessionid="": session)
    posts = collector._collect_sync([])
    texts = [p.text for p in posts]
    assert texts == ["Water cut notice", "Still no water in Adajan"]   # empty caption skipped
    post, comment = posts
    assert post.location == "Surat" and post.author_followers == 5000
    assert post.url == "https://www.instagram.com/p/AAA/"
    assert comment.url == "https://www.instagram.com/p/AAA/c/c1/"
    assert comment.location == "Surat"
    # Already seen: nothing new next cycle.
    assert collector._collect_sync([]) == []


def test_rate_limit_parks_the_route(monkeypatch, collector):
    session = FakeSession({"web_profile_info": FakeResponse(429)})
    monkeypatch.setattr(uf, "make_session", lambda sessionid="": session)
    assert collector._collect_sync([]) == []
    assert not collector.is_configured()
    assert "429" in collector.status_detail()


def test_disabled_by_setting(monkeypatch, collector):
    monkeypatch.setattr(settings, "IG_USERFEED_ENABLED", False)
    assert not collector.is_configured()


class CookieJar(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def _signed_in(session):
    session.cookies = CookieJar(sessionid="abc")
    return session


V1_COMMENTS = {"status": "ok", "comments": [
    {"pk": "c1", "text": "Still no water in Adajan", "created_at": 1_760_000_100,
     "comment_like_count": 7, "child_comment_count": 1,
     "user": {"pk": "9", "username": "resident", "is_verified": False},
     "preview_child_comments": [
         {"pk": "c2", "text": "Same in Vesu", "created_at": 1_760_000_200,
          "user": {"pk": "10", "username": "neighbour"}}]}]}


def test_live_session_reads_v1_comments_with_replies():
    session = _signed_in(FakeSession({"/comments/": FakeResponse(payload=V1_COMMENTS)}))
    nodes = uf.fetch_comments(session, "AAA", 5, media_id="111")
    url, params, headers = session.requests[0]
    assert url == "https://www.instagram.com/api/v1/media/111/comments/"
    assert headers == {"x-ig-app-id": uf.IG_APP_ID}
    assert [(n["id"], n["reply_to"]) for n in nodes] == [("c1", ""), ("c2", "c1")]
    assert nodes[0]["edge_liked_by"]["count"] == 7 and nodes[0]["owner"]["username"] == "resident"


def test_v1_failure_falls_back_to_the_query_hash():
    payload = {"data": {"shortcode_media": {"edge_media_to_comment": {"edges": [
        {"node": {"id": "c1", "text": "Road is broken", "owner": {"username": "r"}}}]}}}}
    session = _signed_in(FakeSession({"graphql/query": FakeResponse(payload=payload)}))
    nodes = uf.fetch_comments(session, "AAA", 5, media_id="111")   # v1 answers 404
    assert nodes[0]["text"] == "Road is broken"


def test_logged_out_cookie_is_dropped_and_the_cycle_goes_on(monkeypatch, collector):
    monkeypatch.setattr(settings, "IG_SESSIONID", "dead-cookie")
    login = FakeResponse(200, text="<html>login</html>",
                         url="https://www.instagram.com/accounts/login/?next=/")
    profile = FakeResponse(payload=_profile("suratcitypolice",
                                            nodes=[_node("AAA", "Water cut notice")]))
    cookies_seen = []

    def make(sessionid=""):
        cookies_seen.append(sessionid)
        s = FakeSession({"web_profile_info": login if sessionid else profile})
        s.cookies = CookieJar(sessionid=sessionid) if sessionid else CookieJar()
        return s

    monkeypatch.setattr(uf, "make_session", make)
    posts = collector._collect_sync([])
    assert cookies_seen == ["dead-cookie", ""]
    assert [p.text for p in posts] == ["Water cut notice"]
    assert collector.is_configured()   # not parked: signed out still works
    assert "IG_SESSIONID is logged out" in collector.status_detail()
    # The dead cookie is not tried again next cycle…
    collector._collect_sync([])
    assert cookies_seen[-1] == ""
    # …but a fresh one is.
    monkeypatch.setattr(settings, "IG_SESSIONID", "fresh-cookie")
    collector._collect_sync([])
    assert cookies_seen[-2] == "fresh-cookie"   # tried (and, here, also dead)


def test_refusal_mid_cycle_keeps_what_was_read(monkeypatch, collector):
    monkeypatch.setattr(settings, "IG_SEED_USERNAMES_RAW",
                        ["suratcitypolice:Surat", "rajkotpolice:Rajkot"])

    def reply(params):
        if params.get("username") == "suratcitypolice":
            return FakeResponse(payload=_profile("suratcitypolice",
                                                 nodes=[_node("AAA", "Water cut notice")]))
        return FakeResponse(429)

    session = FakeSession({"web_profile_info": reply})
    monkeypatch.setattr(uf, "make_session", lambda sessionid="": session)
    posts = collector._collect_sync([])
    assert [p.text for p in posts] == ["Water cut notice"]
    assert not collector.is_configured()


def test_captionless_post_still_has_its_comments_read(monkeypatch, collector):
    comments = {"data": {"shortcode_media": {"edge_media_to_comment": {"edges": [
        {"node": {"id": "c9", "text": "Who will fix this pothole?",
                  "owner": {"username": "resident"}}}]}}}}
    session = FakeSession({
        "web_profile_info": FakeResponse(payload=_profile(
            "suratcitypolice", nodes=[_node("PHOTO", "", comments=4)])),
        "graphql/query": FakeResponse(payload=comments),
    })
    monkeypatch.setattr(uf, "make_session", lambda sessionid="": session)
    posts = collector._collect_sync([])
    assert [p.text for p in posts] == ["Who will fix this pothole?"]
    assert posts[0].url == "https://www.instagram.com/p/PHOTO/c/c9/"
