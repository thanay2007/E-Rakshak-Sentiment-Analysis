"""Account discovery: the roster, Facebook page search, Instagram locations.

The seed lists cover what the four cities announce. Discovery covers everyone
else — the influencers, food pages, college pages and neighbourhood desks that
carry how a city actually feels — and because it is automatic, the ways it can
go wrong are quiet ones:

  1. "Surat" is also a province of Thailand and a district of Bangladesh, and
     both rank above the real city in Facebook's and Instagram's search. A
     roster that swallows them spends the whole crawl budget abroad while the
     dashboard shows four cities being monitored.
  2. Discovery only ever adds. Without pruning, one location feed's worth of
     private and nine-follower accounts sits in the rotation forever, and the
     read budget drains into accounts that will never return a post.
  3. A discovered account must never displace a configured one. Seeds are a
     deliberate choice; discoveries are a guess, and a guess that crowds out
     the police page has made the system worse.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.crawlers import facebook_discover as fbd
from app.crawlers import roster
from app.crawlers.facebook_scrape import FacebookScrapeCollector
from app.crawlers.instagrapi_ig import InstagrapiCollector

# --- the roster ------------------------------------------------------------


def test_seeds_come_first_and_a_rediscovered_seed_keeps_its_city():
    roster.add("facebook", [{"handle": "ourvadodara", "city": "Vadodara"},
                            {"handle": "suratcitypolice", "city": "Gujarat"}])
    merged = roster.merged("facebook", [("suratcitypolice", "Surat")])
    assert merged[0] == ("suratcitypolice", "Surat")   # the configured tag wins
    assert ("ourvadodara", "Vadodara") in merged
    assert len(merged) == 2                             # and nothing is doubled


def test_a_known_handle_keeps_the_size_it_was_found_at():
    roster.add("instagram", [{"handle": "surat_foodie", "followers": 12_000}])
    roster.add("instagram", [{"handle": "surat_foodie", "followers": 3}])
    entries = roster.entries("instagram")
    assert len(entries) == 1
    assert entries[0]["followers"] == 12_000


def test_prune_drops_only_what_it_is_given():
    roster.add("instagram", [{"handle": "keep_me"}, {"handle": "drop_me"}])
    assert roster.prune("instagram", ["DROP_ME"]) == 1   # case-insensitive
    assert [e["handle"] for e in roster.entries("instagram")] == ["keep_me"]


def test_the_cap_drops_the_newest_arrivals(monkeypatch):
    """Not the oldest. An account that has been in the rotation for weeks has
    been earning its slot; the one added a second ago has not."""
    monkeypatch.setattr(settings, "ROSTER_MAX_ENTRIES", 2)
    roster.add("instagram", [{"handle": "first"}, {"handle": "second"}])
    roster.add("instagram", [{"handle": "third"}])
    assert [e["handle"] for e in roster.entries("instagram")] == ["first", "second"]


def test_a_corrupt_roster_does_not_take_a_platform_offline(isolated_roster):
    isolated_roster.write_text("{ this is not json", encoding="utf-8")
    assert roster.entries("facebook") == []
    assert roster.merged("facebook", [("suratcitypolice", "Surat")]) == [
        ("suratcitypolice", "Surat")]


# --- Facebook page search --------------------------------------------------

def _card(slug: str, name: str, body: str) -> str:
    return f"""
    <div role="article">
      <a href="https://www.facebook.com/{slug}?__tn__=%3C">{name}</a>
      <div>{body}</div>
    </div>"""


SEARCH_HTML = "<div>" + "".join([
    _card("News4Surat", "Surat News Live",
          "Media/news company | Surat, Gujarat, India | 48,300 followers"),
    # Same name, wrong continent — Facebook ranks these above the real city.
    _card("prd.suratthani", "PRD Surat Thani",
          "Government organization | Surat Thani, Thailand | 91,000 followers"),
    _card("surat.bangladesh", "Surat Bangladesh",
          "Community | Sylhet, Bangladesh | 12,000 followers"),
    # Real city, too small to be worth a full page load every rotation.
    _card("suratpaanshop", "Surat Paan Shop",
          "Grocery store | Surat, Gujarat, India | 84 followers"),
    # Facebook's own furniture, which is not a page at all.
    _card("settings", "Settings", "Surat, Gujarat, India | 900 followers"),
]) + "</div>"


def test_page_search_keeps_the_city_and_rejects_its_namesakes_abroad():
    found = fbd._parse_results(SEARCH_HTML, ["Surat"], 500, "surat news")
    assert [r["handle"] for r in found] == ["News4Surat"]
    assert found[0] == {"handle": "News4Surat", "city": "Surat",
                        "name": "Surat News Live", "followers": 48_300,
                        "category": "Media/news company",
                        "source": "fb-search:surat news"}


def test_page_search_honours_the_follower_floor():
    handles = {r["handle"] for r in fbd._parse_results(SEARCH_HTML, ["Surat"], 50,
                                                       "surat")}
    assert "suratpaanshop" in handles     # above the lowered floor
    assert "settings" not in handles      # never, at any floor


def test_a_gujarati_script_page_needs_no_english_address():
    """"અમદાવાદ" is not a place in Thailand, so the second signal the English
    filter insists on would only lose local-language pages."""
    html = _card("amdavad.updates", "અમદાવાદ અપડેટ્સ", "News | 22,000 followers")
    found = fbd._parse_results(html, ["Ahmedabad"], 500, "અમદાવાદ news")
    assert [r["city"] for r in found] == ["Ahmedabad"]


# --- Facebook: discovered pages in the rotation -----------------------------

def test_discovered_pages_join_the_seed_rotation(monkeypatch):
    monkeypatch.setattr(settings, "FB_PAGE_IDS_RAW", ["suratcitypolice:Surat"])
    collector = FacebookScrapeCollector()
    assert collector._pages() == [("suratcitypolice", "Surat")]
    roster.add("facebook", [{"handle": "News4Surat", "city": "Surat"}])
    assert collector._pages() == [("suratcitypolice", "Surat"),
                                  ("News4Surat", "Surat")]


def test_a_dead_discovered_page_is_dropped_but_a_seed_is_not(monkeypatch):
    monkeypatch.setattr(settings, "FB_PAGE_IDS_RAW", ["suratcitypolice:Surat"])
    roster.add("facebook", [{"handle": "News4Surat", "city": "Surat"}])
    collector = FacebookScrapeCollector()
    configured = {"suratcitypolice"}
    for _ in range(4):
        collector._strike("News4Surat", configured)
        collector._strike("suratcitypolice", configured)
    assert collector._pages() == [("suratcitypolice", "Surat")]


# --- Instagram: locations and search ---------------------------------------

def _place(pk: int, name: str, address: str, city: str = "", lat=0.0, lng=0.0):
    return types.SimpleNamespace(pk=pk, name=name, address=address, city=city,
                                 lat=lat, lng=lng)


def _media(pk: str, username: str, caption: str):
    return types.SimpleNamespace(
        pk=pk, id=f"{pk}_1", code=f"C{pk}", caption_text=caption,
        taken_at=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
        user=types.SimpleNamespace(pk=f"u{pk}", username=username,
                                   full_name=username, is_verified=False),
        location=None, like_count=5, comment_count=0, play_count=0,
        view_count=0, video_url=None, thumbnail_url=None, resources=[])


class _Client:
    """Only the private-API calls the legs under test actually make."""

    def __init__(self, *, places=(), medias=(), users=(), followers=5_000):
        self.places, self.medias, self.users = list(places), list(medias), list(users)
        self.followers = followers
        self.searched: list[str] = []
        self.read: list[str] = []

    def fbsearch_places(self, query):
        self.searched.append(query)
        return self.places

    def location_medias_recent(self, pk, amount=0):
        return self.medias

    def search_users(self, query, amount=0):
        self.searched.append(query)
        return self.users

    def user_info_by_username(self, username):
        self.read.append(username)
        return types.SimpleNamespace(pk=f"pk_{username}", follower_count=self.followers,
                                     is_verified=False, full_name=username)

    def user_medias(self, pk, amount=0):
        return self.medias


@pytest.fixture
def surat_only(monkeypatch):
    monkeypatch.setattr(settings, "TARGET_CITIES", ["Surat"])
    for key, value in (("IG_LOCATIONS_PER_CYCLE", 4), ("IG_LOCATIONS_PER_CITY", 6),
                       ("IG_LOCATION_MEDIA_LIMIT", 20), ("IG_LOCATION_TTL_HOURS", 168),
                       ("IG_DISCOVERY_QUERIES_PER_CYCLE", 1),
                       ("IG_DISCOVERED_ACCOUNTS_PER_CYCLE", 4),
                       ("IG_DISCOVERED_MIN_FOLLOWERS", 300),
                       ("IG_SEED_USERNAMES_RAW", [])):
        monkeypatch.setattr(settings, key, value)
    return monkeypatch


def test_place_search_rejects_the_city_of_the_same_name_abroad(surat_only):
    client = _Client(places=[
        _place(1, "Surat Railway Station", "Surat, Gujarat, India", "Surat"),
        _place(2, "Surat Thani Airport", "Surat Thani, Thailand", "Surat Thani"),
        _place(3, "Dumas Beach", "Dumas Road, Vesu", "Vesu"),  # no city, no coords
    ])
    places = InstagrapiCollector()._places_sync(client, "Surat")
    assert [pk for pk, _city, _name in places] == [1]


def test_a_places_coordinates_outrank_its_name(surat_only):
    """Instagram place records are frequently a bare name with a pin and no
    address at all — and a pin cannot be in two countries. Dumas Beach is in
    Surat and says so nowhere; Surat Thani says "Surat" and is in Thailand."""
    client = _Client(places=[
        _place(4, "Dumas Beach", "", lat=21.08, lng=72.71),
        _place(5, "Surat Beach Resort", "", lat=9.14, lng=99.33),   # Thailand
        _place(6, "Kankaria Lake", "", lat=23.00, lng=72.60),        # Ahmedabad
    ])
    found = {pk for pk, _c, _n in InstagrapiCollector()._places_sync(client, "Surat")}
    assert 4 in found and 5 not in found
    # Inside Gujarat but in the wrong city: the pin says India, and a place
    # search for "Surat Gujarat" is trusted to have ranked by relevance. Being
    # generous here is deliberate — a Gujarat post filed under a neighbouring
    # city is still a Gujarat post, and geo enrichment re-reads the text
    # downstream.
    assert 6 in found


def test_location_media_is_tagged_with_the_city_it_was_found_in(surat_only):
    client = _Client(
        places=[_place(1, "Surat Railway Station", "Surat, Gujarat, India")],
        medias=[_media("m1", "surat_foodie", "queue outside the station again")])
    collector = InstagrapiCollector()
    harvest = collector._locations_sync(client)
    assert [city for _m, city, _p in harvest] == ["Surat"]
    post = collector._media_to_post(*harvest[0])
    assert post.location == "Surat"


def test_everyone_a_location_feed_turns_up_lands_in_the_roster(surat_only):
    """The strongest discovery signal available: they posted from a place in
    this city, this week."""
    client = _Client(
        places=[_place(1, "Surat Railway Station", "Surat, Gujarat, India")],
        medias=[_media("m1", "surat_foodie", "chai"),
                _media("m2", "vesu_diaries", "traffic"),
                _media("m3", "surat_foodie", "again")])
    InstagrapiCollector()._locations_sync(client)
    assert {e["handle"] for e in roster.entries("instagram")} == {
        "surat_foodie", "vesu_diaries"}
    assert {e["city"] for e in roster.entries("instagram")} == {"Surat"}


def test_account_search_records_public_handles_only(surat_only):
    client = _Client(users=[
        types.SimpleNamespace(username="surat_food_blog", full_name="Surat Food",
                              is_private=False),
        types.SimpleNamespace(username="private_person", full_name="P",
                              is_private=True),
        types.SimpleNamespace(username="not a handle!", full_name="X",
                              is_private=False),
    ])
    InstagrapiCollector()._search_accounts_sync(client)
    assert [e["handle"] for e in roster.entries("instagram")] == ["surat_food_blog"]


def test_a_discovered_account_too_small_to_read_is_dropped(surat_only):
    roster.add("instagram", [{"handle": "nine_followers", "city": "Surat"}])
    client = _Client(medias=[_media("m1", "nine_followers", "hello")], followers=9)
    assert InstagrapiCollector()._discovered_accounts_sync(client) == []
    assert roster.entries("instagram") == []


def test_a_discovered_account_worth_reading_stays(surat_only):
    roster.add("instagram", [{"handle": "surat_foodie", "city": "Surat"}])
    client = _Client(medias=[_media("m1", "surat_foodie", "best khaman in Surat")],
                     followers=44_000)
    harvest = InstagrapiCollector()._discovered_accounts_sync(client)
    assert [city for _m, city, _p in harvest] == ["Surat"]
    assert [e["handle"] for e in roster.entries("instagram")] == ["surat_foodie"]


def test_discovery_never_spends_the_seed_budget(surat_only):
    """The two rotations are separate on purpose: a roster grown to hundreds
    must not push the civic pages out of the cycle."""
    surat_only.setattr(settings, "IG_SEED_USERNAMES_RAW", ["suratcitypolice:Surat"])
    roster.add("instagram", [{"handle": "suratcitypolice", "city": "Surat"},
                             {"handle": "surat_foodie", "city": "Surat"}])
    client = _Client(medias=[_media("m1", "x", "y")], followers=44_000)
    InstagrapiCollector()._discovered_accounts_sync(client)
    assert client.read == ["surat_foodie"]  # the seed is read by the seed leg


# --- the five languages, on the discovery side ------------------------------
#
# The parser handles all five (see test_facebook_scrape). None of that matters
# if the pages that post in them are never found: a page called "સુરત સમાચાર"
# contains the string "Surat" nowhere at all, and an English-only query matrix
# reaches only the English-named half of a Gujarati city.

def test_the_query_matrix_covers_every_script_the_cities_are_written_in():
    queries = fbd._queries(["Surat"], fbd.CATEGORY_TERMS, statewide=False)
    assert "સુરત સમાચાર" in queries      # Gujarati script, Gujarati term
    assert "सूरत समाचार" in queries      # Hindi script, Hindi term
    assert "Surat samachar" in queries   # romanized — Hinglish/Gujlish pages
    assert "Surat khabar" in queries
    assert "Surat news" in queries       # and English


def test_an_alias_is_searched_in_its_own_script():
    """A Gujarati city name paired with English category words finds far less
    than one paired with "સમાચાર", and the reverse for Devanagari."""
    assert fbd._alias_terms("સુરત") == fbd.ALIAS_TERMS_GUJARATI
    assert fbd._alias_terms("सूरत") == fbd.ALIAS_TERMS_HINDI
    assert fbd._alias_terms("Baroda") == fbd.ALIAS_TERMS_LATIN


def test_a_page_named_only_in_an_indic_script_is_still_matched_to_its_city():
    """Its card has no English city name anywhere — the page name is the only
    signal, and dropping it would lose exactly the local-language pages this
    matrix was widened to find."""
    for name, city in (("સુરત સમાચાર", "Surat"), ("सूरत समाचार", "Surat"),
                       ("અમદાવાદ અપડેટ્સ", "Ahmedabad")):
        html = _card("localnewspage", name, "News | 22,000 followers")
        found = fbd._parse_results(html, ["Surat", "Ahmedabad"], 500, "q")
        assert [r["city"] for r in found] == [city], name


# --- endpoints Instagram will not extend to this account --------------------
#
# Measured against the live API: a session that reads seed profiles, their
# media and their comments perfectly well is still refused `tags/`,
# `fbsearch/` and `locations/` with login_required. That is Instagram
# withholding the *discovery* surfaces from an account it does not trust yet,
# not a bad session — and re-asking every cycle is what turned this account's
# refusals into a checkpoint.

class _GatedClient(_Client):
    def fbsearch_places(self, query):
        raise Exception("login_required")

    def search_users(self, query):
        raise Exception("login_required")

    def location_medias_recent(self, pk, amount=0):
        raise Exception("login_required")


def test_a_refused_endpoint_is_not_asked_again_this_cycle(surat_only):
    collector = InstagrapiCollector()
    client = _GatedClient()
    assert collector._locations_sync(client) == []
    assert collector._is_gated("place search")
    # A second cycle must not spend a single call on it.
    client.searched.clear()
    assert collector._locations_sync(client) == []
    assert client.searched == []


def test_gating_one_leg_leaves_the_others_collecting(surat_only):
    collector = InstagrapiCollector()
    collector._search_accounts_sync(_GatedClient())
    assert collector._is_gated("account search")
    # The seed pages are read through a different endpoint, which works.
    roster.add("instagram", [{"handle": "surat_foodie", "city": "Surat"}])
    ok = _Client(medias=[_media("m1", "surat_foodie", "khaman")], followers=44_000)
    assert len(collector._discovered_accounts_sync(ok)) == 1


def test_a_real_error_does_not_park_the_leg(surat_only):
    """A timeout is not a refusal. Parking a leg for six hours over one dropped
    connection would quietly halve coverage for the rest of the day."""
    class _Flaky(_Client):
        def fbsearch_places(self, query):
            raise Exception("HTTPSConnectionPool: Read timed out")

    collector = InstagrapiCollector()
    collector._locations_sync(_Flaky())
    assert not collector._is_gated("place search")


def test_account_search_is_called_the_way_instagrapi_declares_it(surat_only):
    """instagrapi's search_users takes the query alone. A stray count argument
    raises TypeError — caught, logged, and the leg is dead for good with
    nothing in the roster to show it."""
    import inspect

    from instagrapi.mixins.fbsearch import FbSearchMixin

    params = list(inspect.signature(FbSearchMixin.search_users).parameters)
    assert params == ["self", "query"], (
        "instagrapi changed search_users; _search_accounts_sync must match")


def test_a_follower_count_is_never_recorded_as_the_pages_category():
    """Cards lead segments with a pin, a bullet or a BOM, so a count anchored
    match lets "📍 1.3K followers" through as the category — 90 of the first
    922 pages discovered were filed under one."""
    card = _card("suratfoodies", "Surat Foodies",
                 "\ufeff | 📍 1.3K followers | Surat, Gujarat, India | "
                 "Food &amp; beverage | 1,300 followers")
    found = fbd._parse_results(card, ["Surat"], 500, "q")
    assert found[0]["category"] == "Food & beverage"
    assert found[0]["followers"] == 1300


def test_discovery_never_starves_the_configured_seed_pages(monkeypatch):
    """A roster of 991 discovered pages at 6 a cycle is a three-day sweep. If
    the seeds shared that rotation, the Surat police page would go from being
    read every half hour to twice a week — coverage bought by losing the pages
    the deployment exists for."""
    monkeypatch.setattr(settings, "FB_PAGE_IDS_RAW", ["suratcitypolice:Surat"])
    monkeypatch.setattr(settings, "FB_SEED_PAGES_PER_CYCLE", 3)
    monkeypatch.setattr(settings, "FB_PAGES_PER_CYCLE", 2)
    roster.add("facebook", [{"handle": f"page{i}", "city": "Surat"}
                            for i in range(50)])
    collector = FacebookScrapeCollector()
    for _ in range(5):                      # five cycles, deep into the roster
        cycle = collector._cycle_pages()
        assert cycle[0] == ("suratcitypolice", "Surat")
        assert len(cycle) == 3              # the seed plus two discoveries


def test_the_discovered_rotation_advances_and_wraps(monkeypatch):
    monkeypatch.setattr(settings, "FB_PAGE_IDS_RAW", [])
    monkeypatch.setattr(settings, "FB_PAGES_PER_CYCLE", 2)
    roster.add("facebook", [{"handle": f"page{i}", "city": "Surat"}
                            for i in range(3)])
    collector = FacebookScrapeCollector()
    seen = [h for _ in range(3) for h, _c in collector._cycle_pages()]
    assert seen == ["page0", "page1", "page2", "page0", "page1", "page2"]


# --- collecting with no account at all --------------------------------------
#
# Instagram's signed-out routes (crawlers/instagram_public.py) are the floor
# under a refused session, and a refused session is a recurring state here
# rather than an exception: the account gets checkpointed, the cookie is
# revoked, the password goes stale. Each of those used to mean Instagram
# contributed nothing until a human noticed.

def _public_post(handle: str, text: str):
    from app.schemas import RawPost
    return RawPost(platform="Instagram", author_handle=handle, author_name=handle,
                   text=text, hashtags=[], location="",
                   engagement={"likes": 1, "shares": 0, "comments": 0, "views": 0},
                   url=f"https://www.instagram.com/p/{handle}/")


def test_a_refused_session_still_collects_signed_out(surat_only, monkeypatch):
    import asyncio

    from app.crawlers import instagram_public
    from app.crawlers.instagrapi_ig import AuthFailed

    collector = InstagrapiCollector()
    monkeypatch.setattr(collector, "_login_sync", lambda: (_ for _ in ()).throw(
        AuthFailed("IG_SESSIONID: session cookie rejected")))
    monkeypatch.setattr(instagram_public, "_session", lambda: None)
    monkeypatch.setattr(instagram_public, "hashtag_medias",
                        lambda tag, limit, session=None: [
                            (f"{tag}-1", _public_post("hu.to.blogger", f"#{tag} chai")),
                            (f"{tag}-2", _public_post("thebhargavi", "મમ્મીની ચપ્પલ"))])

    posts = asyncio.run(collector.collect(["surat"]))
    assert [p.author_handle for p in posts[:2]] == ["hu.to.blogger", "thebhargavi"]
    # The adapter is still honest about the session being refused...
    assert "session cookie rejected" in collector.status_detail()
    # ...and everyone it saw is a live account in the city's conversation.
    assert {e["handle"] for e in roster.entries("instagram")} == {
        "hu.to.blogger", "thebhargavi"}


def test_the_signed_out_route_backs_off_when_rate_limited(surat_only, monkeypatch):
    import asyncio

    from app.crawlers import instagram_public
    from app.crawlers.instagrapi_ig import AuthFailed

    collector = InstagrapiCollector()
    monkeypatch.setattr(collector, "_login_sync", lambda: (_ for _ in ()).throw(
        AuthFailed("refused")))
    monkeypatch.setattr(instagram_public, "_session", lambda: None)
    calls: list[str] = []

    def limited(tag, limit, session=None):
        calls.append(tag)
        raise instagram_public.PublicRateLimited("429")

    monkeypatch.setattr(instagram_public, "hashtag_medias", limited)
    assert asyncio.run(collector.collect(["surat"])) == []
    assert len(calls) == 1               # stopped at the first 429, not per tag
    assert asyncio.run(collector.collect(["surat"])) == []
    assert len(calls) == 1               # and not retried on the next cycle


def test_the_target_cities_are_always_asked_for(surat_only, monkeypatch):
    """A watchlist tuned to a live incident can hold no city tag at all, and
    the whole point of this path is that something still arrives."""
    import asyncio

    from app.crawlers import instagram_public
    from app.crawlers.instagrapi_ig import AuthFailed

    collector = InstagrapiCollector()
    monkeypatch.setattr(collector, "_login_sync", lambda: (_ for _ in ()).throw(
        AuthFailed("refused")))
    monkeypatch.setattr(instagram_public, "_session", lambda: None)
    asked: list[str] = []
    monkeypatch.setattr(instagram_public, "hashtag_medias",
                        lambda tag, limit, session=None: asked.append(tag) or [])
    asyncio.run(collector.collect(["bandh call"]))   # multi-word: not a tag
    assert "surat" in asked


def test_a_throttled_lookup_never_deletes_a_live_account(surat_only):
    """Measured, not hypothetical: Instagram's public profile route rate-limits
    per IP after a handful of calls, and one cycle reading eight discovered
    accounts hit it — deleting nine live Surat accounts whose only fault was
    being eighth in the queue. A 429 says nothing about an account."""
    roster.add("instagram", [{"handle": "gj5_comedy", "city": "Surat"}])

    class _Throttled(_Client):
        def user_info_by_username(self, username):
            raise Exception("Max retries exceeded ... too many 429 error responses")

    collector = InstagrapiCollector()
    assert collector._discovered_accounts_sync(_Throttled()) == []
    assert [e["handle"] for e in roster.entries("instagram")] == ["gj5_comedy"]


def test_an_account_that_really_is_gone_is_still_dropped(surat_only):
    roster.add("instagram", [{"handle": "deleted_account", "city": "Surat"}])

    class _Gone(_Client):
        def user_info_by_username(self, username):
            raise Exception("User not found")

    InstagrapiCollector()._discovered_accounts_sync(_Gone())
    assert roster.entries("instagram") == []


def test_the_signed_out_route_fills_in_for_gated_discovery(surat_only, monkeypatch):
    """A session can read everything it is told to read and still be refused
    every endpoint that finds something new. The credential-free routes are
    not affected by that, so they run alongside rather than only in place of."""
    from app.crawlers import instagram_public

    collector = InstagrapiCollector()
    collector._gated["location feed"] = collector._gated["account search"] = 1e9
    monkeypatch.setattr(instagram_public, "_session", lambda: None)
    monkeypatch.setattr(instagram_public, "hashtag_medias",
                        lambda tag, limit, session=None: [
                            (f"{tag}-1", _public_post("gj5_comedy", f"#{tag} 🤣"))])

    posts = collector._collect_sync(_Client(), ["surat"])
    assert [p.author_handle for p in posts] == ["gj5_comedy"]
