"""The browser-driven Facebook adapter and its place in the registry.

No browser is started here: everything under test is the pure half — turning a
rendered feed into RawPost — which is also the half Facebook breaks. What is
worth guarding:

  1. Adapter precedence. The Graph API adapter and this one both emit
     platform="Facebook". If both ever go active at once, every post is
     ingested twice and every engagement metric in the dashboard doubles.
  2. Comments are role="article" on Facebook, same as posts. A parser that
     does not exclude them scores "Nice pic" as public sentiment about a city.
  3. collect() swallowing failures. A dead session, a missing Chrome and a
     changed selector must all leave the ingestion loop running.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.crawlers import facebook_scrape as fbs
from app.crawlers.facebook_scrape import AuthFailed, FacebookScrapeCollector
from app.crawlers.registry import platform_status

# A cut-down version of what Facebook actually serves: an obfuscated feed post
# with no labelled message container, a comment nested inside it as its own
# role="article", the timestamp carried by the permalink's link text, counts in
# aria-labels, and one real photo alongside an avatar thumbnail.
FEED_HTML = """
<div role="article" aria-posinset="1">
  <h3><a href="/SuratCityPolice/">Surat City Police</a></h3>
  <a href="/SuratCityPolice/posts/pfbid0ABCDEF123?__cft__[0]=xyz&amp;__tn__=-R">4h</a>
  <div dir="auto">Surat City Police</div>
  <div dir="auto">4h &middot; Shared with Public</div>
  <div dir="auto">Traffic diverted on Ring Road after waterlogging near
     Chowk Bazaar. Avoid the stretch until 6 PM. #surat #trafficupdate See less</div>
  <img alt="Profile picture" src="https://scontent.example/v/t1.0-1/avatar_s32x32.jpg"/>
  <img alt="May be an image of road" src="https://scontent.example/v/t39/flood.jpg"/>
  <span aria-label="312 reactions">312</span>
  <span aria-label="See all 41 comments">41 comments</span>
  <span aria-label="18 shares">18 shares</span>
  <div role="article" aria-label="Comment by Ramesh">
    <div dir="auto">Nice work by the police, very good job done here today</div>
  </div>
</div>
"""


# The same page read while *logged in*, which is a different DOM and the one
# that actually collects. The post is an [aria-posinset] wrapper whose body is
# a nested role="article"; the comment is another role="article" inside that
# same wrapper, distinguishable only by its aria-label. The timestamp link's
# href is pure tracking junk, the post id survives only in the photo link, and
# the engagement counts are bare numbers on nodes labelled with the *action*.
LOGGED_IN_HTML = """
<div aria-posinset="7">
  <div role="article">
    <h2><a href="/SuratCityPolice?__cft__[0]=AZx">Surat City Police</a></h2>
    <div dir="auto">સુરત શહેર પોલીસની મોટી સફળતા — ₹1.17 કરોડની છેતરપિંડી
        #gujaratpolice #suratcitypolice</div>
    <a href="?__cft__[0]=AZxgd-hOhK6fOk">15h</a>
    <a href="https://www.facebook.com/photo/?fbid=1060640172988743&amp;set=a.1673585&amp;__cft__[0]=AZx">
      <img alt="May be an image of 2 people" src="https://scontent.example/v/t39/case.jpg"/>
    </a>
    <span aria-label="Like">13</span>
    <span aria-label="Leave a comment">2</span>
  </div>
  <div role="article" aria-label="Comment by D.C. Koli 15 hours ago">
    <div dir="auto">Catch the powerful bluthu satellite hackers, good work by police</div>
    <a href="/SuratCityPolice" aria-label="Wednesday 12 August 2026 at 08:59">15h</a>
    <span aria-label="Like">4</span>
  </div>
</div>
"""


def _articles(collector, html=FEED_HTML, page="suratcitypolice", city="Surat",
              name="Surat City Police", followers=445000):
    return collector._articles_to_posts(html, page, city, name, followers)


def _logged_in_post():
    posts = _articles(FacebookScrapeCollector(), LOGGED_IN_HTML)
    assert len(posts) == 1, f"expected one post, got {len(posts)}"
    return posts[0]


def test_only_one_facebook_adapter_is_ever_active():
    rows = [r for r in platform_status() if r["name"] == "Facebook"]
    assert len(rows) == 1


def test_graph_api_wins_when_a_token_is_set(monkeypatch):
    """Dropping FB_ACCESS_TOKEN into .env must upgrade the source in place, not
    add a second Facebook feed."""
    monkeypatch.setattr(settings, "FB_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(settings, "FB_PAGE_IDS_RAW", ["suratcitypolice:Surat"])
    monkeypatch.setattr(settings, "FB_C_USER", "1234")
    monkeypatch.setattr(settings, "FB_XS", "secret")
    row = next(r for r in platform_status() if r["name"] == "Facebook")
    assert row["adapter"] == "Facebook"


def test_seeds_without_credentials_are_offline_and_say_why(monkeypatch):
    monkeypatch.setattr(settings, "FB_PAGE_IDS_RAW", [])
    monkeypatch.setattr(settings, "FB_C_USER", "1234")
    monkeypatch.setattr(settings, "FB_XS", "secret")
    collector = FacebookScrapeCollector()
    assert not collector.is_configured()
    assert "FB_PAGE_IDS_RAW" in collector.status_detail()


def test_post_is_parsed_from_the_obfuscated_feed():
    post = _articles(FacebookScrapeCollector())[0]
    assert "Traffic diverted on Ring Road" in post.text
    assert post.platform == "Facebook"
    assert post.author_handle == "SuratCityPolice"
    assert post.author_name == "Surat City Police"
    assert post.location == "Surat"
    assert sorted(post.hashtags) == ["surat", "trafficupdate"]


def test_the_pages_own_posts_keep_its_reach_whatever_the_seed_casing():
    """Facebook serves the vanity URL in its own casing ("SuratCityPolice")
    however the seed was configured, so a case-sensitive match makes a page's
    own posts look like reshares and reports their audience as zero."""
    post = _articles(FacebookScrapeCollector())[0]
    assert post.author_followers == 445000


def test_the_expander_label_is_not_part_of_the_message():
    """Clicking "See more" folds the button's own label into the text node —
    every expanded post otherwise ends in "See less"."""
    post = _articles(FacebookScrapeCollector())[0]
    assert not post.text.endswith("See less")


def test_comments_are_not_ingested_as_posts():
    posts = _articles(FacebookScrapeCollector())
    assert len(posts) == 1
    assert "Nice work by the police" not in posts[0].text


def test_permalink_drops_per_impression_tracking():
    """__cft__ changes on every read, so leaving it on makes the same post a
    new URL each cycle — and a new row in every 'top posts' view."""
    post = _articles(FacebookScrapeCollector())[0]
    assert post.url == "https://www.facebook.com/SuratCityPolice/posts/pfbid0ABCDEF123"


def test_a_follower_count_that_has_not_rendered_yet_is_not_cached():
    """The page header arrives after the first posts do. Caching that miss for
    six hours turns a two-second race into a page whose audience reads as zero
    for the rest of the day."""
    collector = FacebookScrapeCollector()
    assert collector._meta("suratcitypolice", "<html><h1>Surat City Police</h1></html>") \
        == ("Surat City Police", 0)
    assert "suratcitypolice" not in collector._page_meta
    assert collector._meta(
        "suratcitypolice",
        "<html><h1>Surat City Police</h1><div>456K followers</div></html>"
    ) == ("Surat City Police", 456000)
    assert "suratcitypolice" in collector._page_meta


def test_engagement_comes_from_aria_labels():
    post = _articles(FacebookScrapeCollector())[0]
    assert post.engagement["likes"] == 312
    assert post.engagement["comments"] == 41
    assert post.engagement["shares"] == 18


def test_avatars_are_not_collected_as_post_media():
    post = _articles(FacebookScrapeCollector())[0]
    assert post.media_urls == ["https://scontent.example/v/t39/flood.jpg"]


def test_relative_timestamp_becomes_a_real_time():
    post = _articles(FacebookScrapeCollector())[0]
    age = datetime.utcnow() - post.created_at
    assert timedelta(hours=3, minutes=50) < age < timedelta(hours=4, minutes=10)


@pytest.mark.parametrize("label", ["", "Sponsored", "unparseable-nonsense"])
def test_unreadable_timestamps_stay_none(label):
    """None is honest — ingestion timestamps at collection. A fabricated date
    would land the post at the wrong place on every trend chart."""
    assert fbs._post_time(label) is None


@pytest.mark.parametrize("raw,expected", [
    ("1.2K", 1200), ("3,456", 3456), ("2M", 2_000_000), ("", 0), ("many", 0),
])
def test_count_parsing(raw, expected):
    assert fbs._count(raw) == expected


def test_chrome_is_stripped_from_the_message():
    """The audience marker and the reaction summary sit in the same text nodes
    as the message; left in, the model scores them as the author's words."""
    text = fbs._clean_text(
        "4h · Shared with Public · Water supply restored in Katargam.\n"
        "All reactions: 199 38 6")
    assert text == "Water supply restored in Katargam."


@pytest.mark.parametrize("body", [
    # A "·" in the message body is not a header separator.
    "Helpline · 100 · is open all night, call it if the road is flooded",
    # "2 d" is the age of a post; "2 days" is the first two words of a sentence.
    "2 days later the road reopened",
])
def test_real_text_that_looks_like_chrome_survives(body):
    assert fbs._clean_text(body) == body


def test_a_multi_segment_header_is_stripped_whole():
    assert fbs._clean_text(
        "August 5 at 3:12 PM · Edited · Public · Bandh call withdrawn"
    ) == "Bandh call withdrawn"


def test_the_same_post_is_only_emitted_once_across_scrolls():
    """Facebook re-renders the same article on every scroll; without the seen
    set each cycle would ingest a page's top post four times."""
    collector = FacebookScrapeCollector()
    assert len(_articles(collector)) == 1
    assert _articles(collector) == []


def test_logged_in_feed_yields_the_post_not_the_comment():
    """The shape that actually collects. Logged in, role="article" marks the
    post body *and* the comments, so the aria-label is the only thing telling
    them apart — this shipped reading "Catch the powerful bluthu satellite
    hackers" as a Surat City Police post with the force's 456K reach."""
    post = _logged_in_post()
    assert "છેતરપિંડી" in post.text
    assert "bluthu" not in post.text
    assert sorted(post.hashtags) == ["gujaratpolice", "suratcitypolice"]


def test_logged_in_permalink_comes_from_the_photo_link():
    """The timestamp link's href is nothing but tracking parameters, which
    clean down to the site root — taking it would give every post on the page
    the same URL. The fbid in the photo link is the only real id on offer."""
    post = _logged_in_post()
    assert post.url == ("https://www.facebook.com/photo/"
                        "?fbid=1060640172988743&set=a.1673585")


def test_logged_in_engagement_pairs_action_labels_with_bare_counts():
    """No "13 reactions" string exists here: the label says which metric and
    the node's text says how much."""
    post = _logged_in_post()
    assert post.engagement["likes"] == 13
    assert post.engagement["comments"] == 2


def test_a_comments_timestamp_is_never_read_as_the_posts():
    """The only *exact* date in this DOM is the commenter's aria-label, and
    it must lose to the post's own "15h" — otherwise a post is dated to
    whenever someone last replied to it.

    On the live page the post's token is rendered lazily and is often absent
    entirely, in which case created_at stays None and ingestion stamps the
    post at collection. That is deliberate: for a feed read minutes old it is
    close, and a fabricated date is not.
    """
    post = _logged_in_post()
    assert post.created_at != datetime(2026, 8, 12, 8, 59)
    age = datetime.utcnow() - post.created_at
    assert timedelta(hours=14, minutes=50) < age < timedelta(hours=15, minutes=10)


def test_a_commenters_reaction_count_is_not_the_posts():
    post = _logged_in_post()
    assert post.engagement["likes"] != 4


def test_collect_never_raises_when_the_browser_cannot_start(monkeypatch):
    def boom():
        raise AuthFailed("fb_cookies.json: session rejected")

    collector = FacebookScrapeCollector()
    monkeypatch.setattr(collector, "_collect_sync", boom)
    assert asyncio.run(collector.collect(["surat"])) == []
    # ...and it latches, so a refused credential is not retried every tick.
    assert not collector.is_configured()
    assert "session rejected" in collector.status_detail()


def test_missing_chrome_is_reported_in_words_an_operator_can_act_on(monkeypatch):
    def boom():
        raise Exception("unknown error: cannot find Chrome binary")

    collector = FacebookScrapeCollector()
    monkeypatch.setattr(collector, "_collect_sync", boom)
    assert asyncio.run(collector.collect([])) == []
    assert "install Google Chrome" in collector.status_detail()


# --- all five languages of the Gujarat feed ------------------------------------
#
# A Surat page posts in Gujarati script, Hindi script, English, and in the two
# romanized forms people actually type — Hinglish and Gujlish. Every one of
# them has to survive the parser with its text intact, because everything
# downstream is built for them: the sentiment model is fine-tuned on all five,
# and language/code_mixed are stored per post. Two ways this breaks quietly and
# neither raises an error — the chrome-stripping regexes eating an Indic body,
# and Facebook serving a machine translation in place of the original.

def _one_post(body: str, tags: str = ""):
    html = f"""
    <div role="article" aria-posinset="1">
      <h3><a href="/suratcitypolice/">Surat City Police</a></h3>
      <a href="/suratcitypolice/posts/pfbid0LANG?__cft__[0]=x">4h</a>
      <div dir="auto">4h &middot; Shared with Public</div>
      <div dir="auto">{body} {tags}</div>
    </div>"""
    posts = _articles(FacebookScrapeCollector(), html)
    assert len(posts) == 1, f"expected one post, got {len(posts)}"
    return posts[0]


@pytest.mark.parametrize("body,expected_language", [
    # Gujarati script
    ("રિંગ રોડ પર પાણી ભરાયું છે, વાહનચાલકોએ બીજો રસ્તો લેવો.", "Gujarati"),
    # Hindi script
    ("रिंग रोड पर पानी भर गया है, कृपया दूसरा रास्ता लें।", "Hindi"),
    # English
    ("Waterlogging on Ring Road, please take an alternate route today.", "English"),
    # Hinglish — romanized Hindi, which is most of what a city page's
    # commenters actually write
    ("Bhai ring road pe bahut paani hai, abhi mat jao wahan", "Hinglish"),
    # Gujlish — romanized Gujarati
    ("Ring road par bau paani chhe, tame biju rasto lo ane maja karo", "Gujlish"),
])
def test_every_language_of_the_feed_survives_the_parser(body, expected_language):
    from app.ml.language import detect_language

    post = _one_post(body)
    assert post.text == body, "the parser altered or truncated the post"
    assert detect_language(post.text)[0] == expected_language


def test_indic_hashtags_are_not_truncated_at_the_first_vowel_sign():
    """#સુરત must not arrive as #સ. Trend counting is done on these."""
    post = _one_post("રસ્તો બંધ છે", tags="#સુરત #વરસાદ")
    assert sorted(post.hashtags) == sorted(["સુરત", "વરસાદ"])


def test_a_gujarati_body_is_not_eaten_by_the_chrome_stripper():
    """The header-stripping regexes match English chrome by shape. Applied to
    an Indic body they must do nothing at all — an over-eager prefix rule
    silently deletes the first clause of every Gujarati post, and the post
    still looks fine in the feed."""
    body = "૨ દિવસ પછી રસ્તો ફરી ખુલ્લો થયો · વાહનવ્યવહાર સામાન્ય"
    assert _one_post(body).text == body


def test_the_original_language_is_restored_before_reading():
    """Facebook shows a machine translation, not the source, whenever the
    account has automatic translation on — and the crawler's UI is pinned to
    English, so every Gujarati and Hindi post qualifies. "See original" must
    therefore be clicked; "See translation" must never be, since that causes
    the substitution instead of undoing it."""
    assert "see original" in fbs._SEE_MORE_JS
    assert "see translation" not in fbs._SEE_MORE_JS


def test_the_translation_affordance_is_not_part_of_the_message():
    post = _one_post("રસ્તો બંધ છે See original")
    assert post.text == "રસ્તો બંધ છે"


# ── auth: the session handshake ─────────────────────────────────────────────
#
# Not the parsing half, but the half that decides whether there is anything to
# parse. Both cases below were live failures where a *working* credential was
# reported as expired, and neither is visible from the outside: the adapter
# just says Facebook is offline and stops.

class _RecordingDriver:
    """The four driver calls `_apply_cookies` makes, in the order it makes
    them. Enough to assert the handshake's shape without starting Chrome."""

    def __init__(self):
        self.calls: list[str] = []
        self.cookies: list[dict] = [
            # what the persistent profile is holding: a session Facebook has
            # already refused, which is the state that triggers the bug
            {"name": "c_user", "value": "old"}, {"name": "xs", "value": "dead"},
            {"name": "datr", "value": "device"},
        ]

    def get(self, url):
        self.calls.append(f"get:{url}")

    def delete_all_cookies(self):
        self.calls.append("clear")
        self.cookies = []

    def add_cookie(self, cookie):
        self.calls.append(f"add:{cookie['name']}")
        self.cookies.append(cookie)

    def get_cookies(self):
        return self.cookies


def test_a_stale_session_is_cleared_before_a_new_one_is_applied():
    """Adding a fresh c_user/xs on top of the profile's dead pair does not
    replace the session — Facebook drops both and serves the login page, so a
    correctly-copied cookie is reported as "expired or revoked" and whoever is
    debugging goes back to the browser to copy it again."""
    driver = _RecordingDriver()
    FacebookScrapeCollector()._apply_cookies(
        driver, [{"name": "c_user", "value": "fresh"},
                 {"name": "xs", "value": "fresh"}])

    assert "clear" in driver.calls, "the profile's dead session was left in place"
    # Clearing has to happen after the domain is loaded (add_cookie needs it)
    # and before anything is added, or it wipes what we just applied.
    assert driver.calls.index("clear") > driver.calls.index("get:https://www.facebook.com/")
    assert driver.calls.index("clear") < driver.calls.index("add:c_user")
    assert {c["value"] for c in driver.get_cookies()} == {"fresh"}


def test_pages_are_opened_without_waiting_for_a_load_event():
    """A Facebook feed with a live connection never fires `load`, so a
    normal-strategy `driver.get` burns the full page-load timeout and then
    raises a renderer timeout — against credentials that were working."""
    import inspect

    signature = inspect.signature(FacebookScrapeCollector._build_driver)
    assert signature.parameters["page_load_strategy"].default == "eager"
