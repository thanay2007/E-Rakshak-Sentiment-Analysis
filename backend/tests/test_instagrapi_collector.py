"""The instagrapi Instagram adapter and its place in the registry.

Two things here are easy to break by accident and expensive to notice late:

  1. Adapter precedence. The Graph API adapter and this one both emit
     platform="Instagram". If both ever go active at once, every post is
     ingested twice and every engagement metric in the dashboard doubles.
  2. collect() swallowing failures. Instagram answers a rate-limited account
     with a challenge, not a clean error, and an adapter that raises out of
     collect() stalls the whole ingestion loop — not just Instagram.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.crawlers import instagrapi_ig
from app.crawlers.instagrapi_ig import UNKNOWN, InstagrapiCollector, Profile
from app.crawlers.registry import platform_status


def _media(pk: str = "999", caption: str = "road blocked #surat protest", **kw):
    """A stand-in for instagrapi's Media model — attribute access only, which
    is all the adapter uses."""
    defaults = dict(
        pk=pk, id=f"{pk}_1", code="ABC123", caption_text=caption,
        taken_at=datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc),
        user=types.SimpleNamespace(pk="7788", username="suratcity",
                                   full_name="Surat City", is_verified=True),
        location=types.SimpleNamespace(lat=21.17, lng=72.83),
        like_count=42, comment_count=7, play_count=0, view_count=100,
        video_url=None, thumbnail_url="https://scontent.example/x.jpg",
        resources=[],
    )
    return types.SimpleNamespace(**{**defaults, **kw})


def _comment(pk: str = "c1", text: str = "worst roads in the city", **kw):
    """A stand-in for instagrapi's Comment model."""
    defaults = dict(
        pk=pk, text=text,
        user=types.SimpleNamespace(pk="4321", username="angry_resident",
                                   full_name="A Resident", is_verified=False),
        created_at_utc=datetime(2026, 8, 7, 11, 0, tzinfo=timezone.utc),
        like_count=3,
    )
    return types.SimpleNamespace(**{**defaults, **kw})


def _instagram_row() -> dict:
    return next(r for r in platform_status() if r["name"] == "Instagram")


@pytest.fixture(autouse=True)
def ig_defaults(monkeypatch):
    """Pin the per-cycle budgets, for every test in this file.

    These have defaults in config.py, but `settings` is loaded from .env — and
    parking a leg at 0 is a legitimate operational response to Instagram
    gating an endpoint on a given account. A test that reads the budget from
    whatever the operator last wrote in .env is testing the deployment, not
    the adapter, and turns red for the wrong reason.

    The two user legs default to 0 here so that a test about comments does not
    also silently exercise them against a stub client that has no such
    methods; tests about those legs turn their own budget back on.
    """
    for key, value in (("IG_HASHTAGS_PER_CYCLE", 3),
                       ("IG_COMMENTS_MAX_MEDIA_PER_CYCLE", 8),
                       ("IG_COMMENTS_PER_MEDIA", 20),
                       ("IG_PROFILE_TTL_HOURS", 24),
                       ("IG_WATCHED_ACCOUNTS_PER_CYCLE", 0),
                       ("IG_PROFILE_LOOKUPS_PER_CYCLE", 0)):
        monkeypatch.setattr(settings, key, value)
    # No test may reach the real watchlist table.
    monkeypatch.setattr("app.crawlers.instagrapi_ig.watched_accounts", lambda: [])
    # A stale ig_session.json on the dev box would otherwise make the adapter
    # look configured when the test says it isn't.
    monkeypatch.setattr("app.crawlers.instagrapi_ig.SESSION_FILE",
                        types.SimpleNamespace(exists=lambda: False, name="ig_session.json"))


@pytest.fixture
def ig_env(monkeypatch):
    """Neutral Instagram credentials; each test opts into the keys it needs."""
    for key, value in (("IG_SESSIONID", ""), ("IG_USERNAME", ""), ("IG_PASSWORD", ""),
                       ("IG_ACCESS_TOKEN", ""), ("IG_BUSINESS_ACCOUNT_ID", ""),
                       ("IG_SEED_USERNAMES_RAW", [])):
        monkeypatch.setattr(settings, key, value)
    return monkeypatch


def _profile(pk="7788", followers=5000, verified=False, full_name="Seed Page"):
    """A stand-in for instagrapi's User model, as user_info* returns it."""
    return types.SimpleNamespace(pk=pk, follower_count=followers,
                                 is_verified=verified, full_name=full_name)


# --- precedence: exactly one Instagram adapter is ever live -----------------

def test_graph_api_wins_when_both_are_configured(ig_env):
    ig_env.setattr(settings, "IG_SESSIONID", "sid")
    ig_env.setattr(settings, "IG_ACCESS_TOKEN", "tok")
    ig_env.setattr(settings, "IG_BUSINESS_ACCOUNT_ID", "123")
    assert _instagram_row() == {"name": "Instagram", "online": True, "adapter": "Instagram", "detail": ""}


def test_instagrapi_takes_over_without_a_graph_token(ig_env):
    ig_env.setattr(settings, "IG_SESSIONID", "sid")
    assert _instagram_row()["adapter"] == "Instagram (instagrapi)"


def test_instagram_offline_without_any_credentials(ig_env):
    assert _instagram_row() == {"name": "Instagram", "online": False, "adapter": "", "detail": ""}


def test_password_login_alone_counts_as_configured(ig_env):
    ig_env.setattr(settings, "IG_USERNAME", "burner")
    ig_env.setattr(settings, "IG_PASSWORD", "pw")
    assert InstagrapiCollector().is_configured()
    ig_env.setattr(settings, "IG_PASSWORD", "")  # half a credential is not one
    assert not InstagrapiCollector().is_configured()


# --- auth ------------------------------------------------------------------

def _fake_client_module(monkeypatch, calls, works=("sessionid", "password", "dump")):
    """Stand in for `from instagrapi import Client` inside _login_sync.

    `works` names the routes Instagram would accept, so a test can model the
    situation that actually occurs in the field — a revoked cookie sitting in
    .env above a password that is still good — rather than only the happy path.

    account_info() is the verification call, and it fails unless the route that
    ran before it is one Instagram accepts. That is the whole point: every
    login method here "succeeds" against a dead credential, and only the
    private-API call afterwards tells the truth.
    """
    class FakeClient:
        delay_range = None

        def __init__(self):
            # A loaded dump is a credential in its own right — it either
            # authenticates on its own or it doesn't.
            self._route = "dump"

        def load_settings(self, path):
            calls.append("load_settings")

        def login_by_sessionid(self, sid):
            calls.append("login_by_sessionid")
            self._route = "sessionid"

        def login(self, u, p):
            calls.append("login")
            self._route = "password"

        def account_info(self):
            calls.append("account_info")
            if self._route not in works:
                raise RuntimeError("login_required: You've Been Logged Out")
            return types.SimpleNamespace(username="burner", full_name="B",
                                         follower_count=1)

        def dump_settings(self, path):
            calls.append("dump_settings")

    monkeypatch.setitem(sys.modules, "instagrapi",
                        types.SimpleNamespace(Client=FakeClient))


def test_sessionid_login_reuses_the_stored_device(ig_env, monkeypatch):
    """The dump is loaded before the cookie login, not skipped: it carries the
    device identity, and Instagram treats a familiar device as less suspicious
    than a new one every run. (Skipping it was tried as a fix for the 403
    login_required this account returns and made no difference — a fresh
    device is refused identically, so the block is on the account.)"""
    calls: list[str] = []
    _fake_client_module(monkeypatch, calls)
    ig_env.setattr(settings, "IG_SESSIONID", "sid")
    monkeypatch.setattr("app.crawlers.instagrapi_ig.SESSION_FILE",
                        types.SimpleNamespace(exists=lambda: True, name="ig_session.json"))
    InstagrapiCollector()._login_sync()
    assert calls == ["load_settings", "login_by_sessionid", "account_info",
                     "dump_settings"]


def test_password_login_reuses_the_stored_device(ig_env, monkeypatch):
    """Same for the password route, where device consistency is what keeps a
    re-login from being challenged."""
    calls: list[str] = []
    _fake_client_module(monkeypatch, calls, works=("password",))
    ig_env.setattr(settings, "IG_USERNAME", "burner")
    ig_env.setattr(settings, "IG_PASSWORD", "pw")
    monkeypatch.setattr("app.crawlers.instagrapi_ig.SESSION_FILE",
                        types.SimpleNamespace(exists=lambda: True, name="ig_session.json"))
    InstagrapiCollector()._login_sync()
    # The stale dump is tried first and rejected; the password route that
    # follows still loads it, for the device id.
    assert calls == ["load_settings", "account_info",
                     "load_settings", "login", "account_info", "dump_settings"]


def test_a_dead_sessionid_falls_through_to_the_password_login(ig_env, monkeypatch):
    """The regression that kept Instagram at zero posts for weeks.

    A `sessionid` is the shortest-lived credential of the three and Instagram
    revokes it freely. When the routes were an if/elif on which credential was
    *present*, a stale cookie in .env ended the attempt then and there — the
    working username and password below it were never tried, every leg
    returned [], and nothing said why.
    """
    calls: list[str] = []
    _fake_client_module(monkeypatch, calls, works=("password",))
    ig_env.setattr(settings, "IG_SESSIONID", "3651637614%3Adead%3A11")
    ig_env.setattr(settings, "IG_USERNAME", "burner")
    ig_env.setattr(settings, "IG_PASSWORD", "pw")
    monkeypatch.setattr("app.crawlers.instagrapi_ig.SESSION_FILE",
                        types.SimpleNamespace(exists=lambda: False, name="ig_session.json"))
    assert InstagrapiCollector()._login_sync() is not None
    assert calls == ["login_by_sessionid", "account_info",
                     "login", "account_info", "dump_settings"]


def test_a_login_that_only_looks_successful_is_rejected(ig_env, monkeypatch):
    """instagrapi's own confirmation of a `sessionid` runs against the public
    web endpoint, which answers a revoked cookie with a redirect loop rather
    than an auth error. Only a private-API call settles it, so one is made."""
    calls: list[str] = []
    _fake_client_module(monkeypatch, calls, works=())
    ig_env.setattr(settings, "IG_SESSIONID", "sid")
    monkeypatch.setattr("app.crawlers.instagrapi_ig.SESSION_FILE",
                        types.SimpleNamespace(exists=lambda: False, name="ig_session.json"))
    with pytest.raises(instagrapi_ig.AuthFailed) as caught:
        InstagrapiCollector()._login_sync()
    assert "IG_SESSIONID" in str(caught.value)
    assert "dump_settings" not in calls  # a bad session is never saved


def test_the_adapter_goes_offline_when_no_route_authenticates(ig_env, monkeypatch):
    """Credentials that Instagram refuses are not a configured platform.

    Reporting one as online is what hid this: the console showed Instagram
    green beside four sources that were delivering, while it delivered nothing
    at all. Offline with a reason is the honest state, and the reason is the
    thing an operator can act on.
    """
    calls: list[str] = []
    _fake_client_module(monkeypatch, calls, works=())
    ig_env.setattr(settings, "IG_SESSIONID", "sid")
    monkeypatch.setattr("app.crawlers.instagrapi_ig.SESSION_FILE",
                        types.SimpleNamespace(exists=lambda: False, name="ig_session.json"))

    collector = InstagrapiCollector()
    assert collector.is_configured()          # credentials are present
    # The signed-out fallback runs but finds nothing this cycle, so the
    # adapter's own state is what is under test here.
    monkeypatch.setattr("app.crawlers.instagram_public._session", lambda: None)
    monkeypatch.setattr("app.crawlers.instagram_public.hashtag_medias",
                        lambda *a, **k: [])
    assert asyncio.run(collector.collect(["surat"])) == []
    assert not collector.is_configured()      # ... and refused
    assert "login_required" in collector.status_detail()


# --- failure containment ---------------------------------------------------

def test_collect_returns_empty_when_login_is_challenged():
    c = InstagrapiCollector()

    def _challenge():
        raise RuntimeError("challenge_required")

    c._login_sync = _challenge
    assert asyncio.run(c.collect(["boycott"])) == []
    assert c._client is None, "a failed login must be retried, not cached"


def test_one_broken_hashtag_does_not_lose_the_others():
    c = InstagrapiCollector()

    def _hashtag_medias_recent(tag, amount):
        if tag == "boycott":
            raise RuntimeError("rate limited")
        return [_media(pk=f"pk-{tag}", caption=f"post about #{tag}")]

    client = types.SimpleNamespace(hashtag_medias_recent=_hashtag_medias_recent)
    harvest = c._hashtags_sync(client, ["boycott", "surat"])
    assert [m.pk for m, _city, _f in harvest] == ["pk-surat"]


def test_a_dead_comment_thread_keeps_the_caption_post(ig_env):
    """Comments disabled on one media must not cost us its caption, nor the
    other media in the batch."""
    ig_env.setattr(settings, "IG_COMMENTS_MAX_MEDIA_PER_CYCLE", 5)
    c = InstagrapiCollector()
    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: [
            _media(pk="a", caption="#surat one", comment_count=9),
            _media(pk="b", caption="#surat two", comment_count=4),
        ],
        media_comments=lambda media_id, amount: (
            _ for _ in ()).throw(RuntimeError("comments disabled")),
    )
    posts = c._collect_sync(client, ["surat"])
    assert sorted(p.text for p in posts) == ["#surat one", "#surat two"]


# --- mapping ---------------------------------------------------------------

def test_media_maps_onto_rawpost():
    post = InstagrapiCollector()._media_to_post(
        _media(), "Surat", Profile(pk="7788", followers=5000, verified=True, known=True))
    assert post.platform == "Instagram"
    assert post.author_handle == "suratcity"
    assert post.author_id == "7788", "the numeric pk is what survives a rename"
    assert post.author_verified is True
    assert post.author_followers == 5000
    assert post.hashtags == ["surat"]
    assert post.location == "Surat"
    assert (post.latitude, post.longitude) == (21.17, 72.83)
    assert post.engagement == {"likes": 42, "shares": 0, "comments": 7, "views": 100}
    assert post.url == "https://www.instagram.com/p/ABC123/"
    # The pipeline stores naive UTC; a tz-aware value here poisons every
    # downstream datetime comparison.
    assert post.created_at == datetime(2026, 8, 7, 10, 0)
    assert post.created_at.tzinfo is None


def test_captionless_and_duplicate_media_are_skipped():
    c = InstagrapiCollector()
    assert c._media_to_post(_media(caption="   "), "Surat") is None
    assert c._media_to_post(_media(pk="dup"), "Surat") is not None
    assert c._media_to_post(_media(pk="dup"), "Surat") is None, "seen-set must dedupe"


@pytest.mark.parametrize("caption, expected", [
    # The whitespace split this replaced returned '#surat,#protest' as one
    # unusable token and kept the trailing '.' on the second.
    ("#surat,#protest", ["surat", "protest"]),
    ("roads flooded #rajkot. again", ["rajkot"]),
    # Gujarati and Devanagari tags — the whole point of a Gujarat deployment.
    ("વિરોધ #સુરત #આંદોલન", ["સુરત", "આંદોલન"]),
    ("#आंदोलन जारी", ["आंदोलन"]),
    # Instagram folds case, so the trend counter must not see two tags here.
    ("#Surat and #surat", ["surat"]),
    ("no tags at all", []),
    ("# ", []),
])
def test_hashtags_are_unicode_aware_and_deduped(caption, expected):
    from app.crawlers.instagrapi_ig import _hashtags
    assert _hashtags(caption) == expected


def test_carousel_keeps_every_frame():
    from app.crawlers.instagrapi_ig import _media_urls
    carousel = _media(resources=[
        types.SimpleNamespace(video_url=None, thumbnail_url="https://x.example/1.jpg"),
        types.SimpleNamespace(video_url="https://x.example/2.mp4", thumbnail_url="https://x.example/2.jpg"),
    ])
    assert _media_urls(carousel) == ["https://x.example/1.jpg", "https://x.example/2.mp4"]
    # A single photo has no resources and falls back to the top-level field.
    assert _media_urls(_media()) == ["https://scontent.example/x.jpg"]


# --- comments --------------------------------------------------------------

def test_comment_becomes_a_post_of_its_own():
    post = InstagrapiCollector()._comment_to_post(
        _comment(), "https://www.instagram.com/p/ABC123/", "Surat")
    assert post.platform == "Instagram"
    assert post.author_handle == "angry_resident"
    assert post.author_id == "4321"
    assert post.text == "worst roads in the city"
    assert post.location == "Surat", "a comment inherits its parent's city"
    assert post.engagement["likes"] == 3
    assert post.url == "https://www.instagram.com/p/ABC123/c/c1/"
    assert post.created_at == datetime(2026, 8, 7, 11, 0)
    assert post.created_at.tzinfo is None


def test_comment_and_media_ids_do_not_collide_in_the_seen_set():
    """Comment pks and media pks are separate id spaces. Without the kind
    prefix a comment whose pk matched an already-seen media would vanish."""
    c = InstagrapiCollector()
    assert c._media_to_post(_media(pk="555"), "Surat") is not None
    assert c._comment_to_post(_comment(pk="555"), "https://x/", "Surat") is not None


def test_comments_go_to_the_most_discussed_media_within_budget(ig_env):
    ig_env.setattr(settings, "IG_COMMENTS_MAX_MEDIA_PER_CYCLE", 2)
    c = InstagrapiCollector()
    asked: list[str] = []

    def _media_comments(media_id, amount):
        asked.append(media_id)
        return [_comment(pk=f"c-{media_id}")]

    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: [
            _media(pk="quiet", caption="#surat quiet", comment_count=1),
            _media(pk="loudest", caption="#surat loudest", comment_count=90),
            _media(pk="loud", caption="#surat loud", comment_count=50),
            _media(pk="silent", caption="#surat silent", comment_count=0),
        ],
        media_comments=_media_comments,
    )
    posts = c._collect_sync(client, ["surat"])
    assert asked == ["loudest_1", "loud_1"], "budget spent on the busiest threads"
    assert len(posts) == 4 + 2, "four captions plus one comment from each of two"


def test_comments_disabled_entirely_when_budget_is_zero(ig_env):
    ig_env.setattr(settings, "IG_COMMENTS_MAX_MEDIA_PER_CYCLE", 0)
    c = InstagrapiCollector()

    def _boom(media_id, amount):
        raise AssertionError("must not fetch comments when the budget is 0")

    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: [_media(caption="#surat x", comment_count=9)],
        media_comments=_boom,
    )
    assert len(c._collect_sync(client, ["surat"])) == 1


# --- hashtags: the private route is not always open -------------------------

def test_a_refused_private_hashtag_falls_back_to_the_public_route():
    """Observed live: Instagram answers tags/<name>/sections/ with
    login_required for a freshly-checkpointed burner while the public web
    GraphQL query keeps working. instagrapi offers no fallback of its own —
    hashtag_medias_recent is private-only."""
    c = InstagrapiCollector()
    injected = []

    def _private(tag, amount):
        raise RuntimeError("login_required")

    client = types.SimpleNamespace(
        hashtag_medias_recent=_private,
        inject_sessionid_to_public=lambda: injected.append(True) or True,
        hashtag_medias_paginated_gql=lambda name, amount: (
            [_media(pk="pub1", caption=f"#{name} from the web route")], "cursor"),
    )
    harvest = c._hashtags_sync(client, ["surat"])
    assert [m.caption_text for m, _c, _p in harvest] == ["#surat from the web route"]
    assert injected == [True], "the public client is anonymous without the cookie"


def test_a_non_auth_hashtag_error_is_not_retried_publicly():
    """A rate limit is not a permissions problem — retrying it on the public
    endpoint just spends a second call to fail the same way."""
    c = InstagrapiCollector()

    def _boom(name, amount):
        raise AssertionError("must not fall back on a non-auth error")

    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: (_ for _ in ()).throw(
            RuntimeError("rate limited")),
        inject_sessionid_to_public=lambda: True,
        hashtag_medias_paginated_gql=_boom,
    )
    assert c._hashtags_sync(client, ["surat"]) == []


# --- users: watched accounts ------------------------------------------------

def test_watched_watchlist_accounts_are_collected(ig_env):
    """An officer adds a handle to the watchlist; its posts must show up.

    Before the user leg existed, a watched account was monitored only by
    accident — when it happened to post something matching a keyword.
    """
    ig_env.setattr(settings, "IG_WATCHED_ACCOUNTS_PER_CYCLE", 4)
    ig_env.setattr("app.crawlers.instagrapi_ig.watched_accounts",
                   lambda: ["@rumour_account"])
    c = InstagrapiCollector()
    client = types.SimpleNamespace(
        user_info_by_username=lambda u: _profile(pk="900", followers=12000,
                                                 verified=True, full_name="R A"),
        user_medias=lambda pk, amount: [_media(pk="w1", caption="something #surat")],
        hashtag_medias_recent=lambda tag, amount: [],
    )
    posts = c._collect_sync(client, [])
    assert [p.text for p in posts] == ["something #surat"]
    assert posts[0].author_followers == 12000
    assert posts[0].author_verified is True
    assert posts[0].location == "", "the watchlist says who to watch, never where"


def test_handles_that_cannot_be_instagram_are_never_looked_up(ig_env):
    """The watchlist has no platform column, so its account rows are a mixed
    bag. Spending a private-API call on a wildcard pattern is how the burner
    gets rate-limited for nothing."""
    ig_env.setattr(settings, "IG_WATCHED_ACCOUNTS_PER_CYCLE", 9)
    ig_env.setattr("app.crawlers.instagrapi_ig.watched_accounts", lambda: [
        "desh_sachai_*",          # a wildcard pattern
        "some guy",               # a space is not a handle
        "t.me/gujaratnews",       # a Telegram link
        "x" * 31,                 # over Instagram's 30-char limit
        "good.handle_1",          # the only real one
    ])
    c = InstagrapiCollector()
    asked: list[str] = []

    def _user_info_by_username(u):
        asked.append(u)
        return _profile(pk="1")

    client = types.SimpleNamespace(
        user_info_by_username=_user_info_by_username,
        user_medias=lambda pk, amount: [],
        hashtag_medias_recent=lambda tag, amount: [],
    )
    c._collect_sync(client, [])
    assert asked == ["good.handle_1"]


def test_an_unreadable_account_is_not_retried_every_cycle(ig_env):
    """A deleted or private handle answers with an error. Retrying it on each
    tick is a wasted call per cycle, forever."""
    ig_env.setattr(settings, "IG_WATCHED_ACCOUNTS_PER_CYCLE", 4)
    ig_env.setattr("app.crawlers.instagrapi_ig.watched_accounts", lambda: ["gone_account"])
    c = InstagrapiCollector()
    attempts = []

    def _user_info_by_username(u):
        attempts.append(u)
        raise RuntimeError("User not found")

    client = types.SimpleNamespace(
        user_info_by_username=_user_info_by_username,
        user_medias=lambda pk, amount: [],
        hashtag_medias_recent=lambda tag, amount: [],
    )
    assert c._collect_sync(client, []) == []
    assert c._collect_sync(client, []) == []
    assert attempts == ["gone_account"], "the failure must be remembered"


def test_watched_accounts_rotate_so_every_handle_is_reached(ig_env):
    """With more watched handles than the per-cycle budget, a fixed slice
    would mean the handles past the budget are never read at all."""
    ig_env.setattr(settings, "IG_WATCHED_ACCOUNTS_PER_CYCLE", 2)
    ig_env.setattr("app.crawlers.instagrapi_ig.watched_accounts",
                   lambda: ["acc_a", "acc_b", "acc_c", "acc_d"])
    c = InstagrapiCollector()
    asked: list[str] = []
    client = types.SimpleNamespace(
        user_info_by_username=lambda u: (asked.append(u), _profile(pk=u))[1],
        user_medias=lambda pk, amount: [],
        hashtag_medias_recent=lambda tag, amount: [],
    )
    for _ in range(2):
        c._collect_sync(client, [])
    assert asked == ["acc_a", "acc_b", "acc_c", "acc_d"]


def test_hashtags_rotate_so_the_whole_watchlist_is_covered():
    """Regression: the slice was always terms[:3], so a watchlist's 4th term
    onwards was never queried once."""
    c = InstagrapiCollector()
    asked: list[str] = []
    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: (asked.append(tag), [])[1])
    terms = ["surat", "rajkot", "bandh", "curfew", "protest"]
    for _ in range(2):
        c._hashtags_sync(client, terms)
    assert asked[:3] == ["surat", "rajkot", "bandh"]
    assert asked[3:] == ["curfew", "protest", "surat"], "must wrap, not restart"


# --- users: author enrichment -----------------------------------------------

def test_a_hashtag_author_gets_a_real_follower_count(ig_env):
    """Media found through a hashtag carries a UserShort — no follower count
    at all — so without a lookup every viral stranger is ingested as an
    account with zero reach and scored accordingly."""
    ig_env.setattr(settings, "IG_PROFILE_LOOKUPS_PER_CYCLE", 3)
    c = InstagrapiCollector()
    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: [_media(pk="h1", caption="#surat viral")],
        user_info=lambda pk: _profile(pk=pk, followers=88000, verified=True,
                                      full_name="Loud Voice"),
    )
    posts = c._collect_sync(client, ["surat"])
    assert posts[0].author_followers == 88000
    assert posts[0].author_name == "Loud Voice"


def test_profile_budget_goes_to_the_highest_engagement_authors(ig_env):
    ig_env.setattr(settings, "IG_PROFILE_LOOKUPS_PER_CYCLE", 1)
    c = InstagrapiCollector()
    asked: list[str] = []

    def _user(pk_, likes):
        return _media(pk=f"m{pk_}", caption=f"#surat {pk_}", like_count=likes,
                      comment_count=0,
                      user=types.SimpleNamespace(pk=pk_, username=f"u{pk_}",
                                                 full_name="", is_verified=None))

    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: [_user("quiet", 3), _user("loud", 900)],
        user_info=lambda pk: (asked.append(pk), _profile(pk=pk, followers=1))[1],
    )
    c._collect_sync(client, ["surat"])
    assert asked == ["loud"]


def test_a_known_profile_is_not_looked_up_twice(ig_env):
    ig_env.setattr(settings, "IG_PROFILE_LOOKUPS_PER_CYCLE", 5)
    c = InstagrapiCollector()
    asked: list[str] = []
    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: [
            _media(pk=f"m{len(c._seen)}", caption=f"#surat {len(c._seen)}")],
        user_info=lambda pk: (asked.append(pk), _profile(pk=pk, followers=7))[1],
    )
    c._collect_sync(client, ["surat"])
    c._collect_sync(client, ["surat"])
    assert asked == ["7788"], "the cached profile must serve the second cycle"


def test_a_seed_account_is_never_enriched_again(ig_env):
    """Its profile came back with the media; a second lookup is pure waste."""
    ig_env.setattr(settings, "IG_SEED_USERNAMES_RAW", ["suratcity:Surat"])
    ig_env.setattr(settings, "IG_PROFILE_LOOKUPS_PER_CYCLE", 5)
    c = InstagrapiCollector()

    def _boom(pk):
        raise AssertionError("a resolved account must not be looked up again")

    client = types.SimpleNamespace(
        user_info_by_username=lambda u: _profile(followers=5000),
        user_medias=lambda pk, amount: [_media()],
        hashtag_medias_recent=lambda tag, amount: [],
        user_info=_boom,
    )
    assert c._collect_sync(client, [])[0].author_followers == 5000


def test_an_unenriched_author_falls_back_to_the_media_user(ig_env):
    """With no lookup budget the post still ships — it just keeps whatever the
    embedded UserShort knew."""
    ig_env.setattr(settings, "IG_PROFILE_LOOKUPS_PER_CYCLE", 0)
    c = InstagrapiCollector()
    client = types.SimpleNamespace(
        hashtag_medias_recent=lambda tag, amount: [_media(caption="#surat x")])
    post = c._collect_sync(client, ["surat"])[0]
    assert post.author_handle == "suratcity"
    assert post.author_followers == 0
    assert post.author_verified is True, "from the media's own user object"


def test_unknown_profile_does_not_overwrite_a_verified_flag():
    post = InstagrapiCollector()._media_to_post(_media(), "Surat", UNKNOWN)
    assert post.author_verified is True
    assert post.author_followers == 0


def test_seed_followers_survive_the_account_cache(ig_env):
    """Regression: the follower count was read only on the first sighting of a
    seed account, so every later cycle reported the account as having zero."""
    ig_env.setattr(settings, "IG_SEED_USERNAMES_RAW", ["suratcity:Surat"])
    ig_env.setattr(settings, "IG_COMMENTS_MAX_MEDIA_PER_CYCLE", 0)
    c = InstagrapiCollector()
    client = types.SimpleNamespace(
        user_info_by_username=lambda u: types.SimpleNamespace(pk="7788", follower_count=5000),
        user_medias=lambda pk, amount: [_media(pk=f"m{pk}-{len(c._seen)}")],
        hashtag_medias_recent=lambda tag, amount: [],
    )
    first = c._collect_sync(client, [])
    second = c._collect_sync(client, [])
    assert first[0].author_followers == 5000
    assert second[0].author_followers == 5000, "cached account lost its follower count"
