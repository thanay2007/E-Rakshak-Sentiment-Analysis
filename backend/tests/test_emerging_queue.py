# -*- coding: utf-8 -*-
"""What is allowed into the unverified-rumour triage queue.

Every case here is a post that was actually in the queue on live data, or the
kind of post the queue exists for. The queue is only worth opening if being on
it means something, so the gates are tested from both sides: what must get in,
and what must never.
"""
import math

import pytest

from app.services import emerging


class FakePost:
    """The column subset `_compute` selects, which is all the gates read."""

    def __init__(self, **kw):
        self.id = kw.get("id", "p1")
        self.platform = kw.get("platform", "X")
        self.author_handle = kw.get("author_handle", "a_citizen")
        self.author_name = kw.get("author_name", "")
        self.author_followers = kw.get("author_followers", 400)
        self.author_verified = kw.get("author_verified", False)
        self.text = kw.get("text", "")
        self.translation = kw.get("translation", "")
        self.sentiment_label = kw.get("sentiment_label", "negative")
        self.concern_score = kw.get("concern_score", 50.0)
        self.engagement = kw.get("engagement", {})
        self.fact_check = kw.get("fact_check", {})
        self.url = kw.get("url", "")
        self.location = kw.get("location", "Surat")
        self.language = kw.get("language", "English")
        self.intent = kw.get("intent", "informational")
        self.hashtags = kw.get("hashtags", [])
        self.created_at = kw.get("created_at", None)


# ── the claim gate ──────────────────────────────────────────────────────────

def test_a_grievance_is_a_claim():
    post = FakePost(text="Four doctors tormented a fellow doctor to death at "
                         "the civil hospital and nobody has been suspended")
    assert emerging._claim_check(post) == ""


def test_praise_is_never_a_rumour():
    """A queue asking an officer to check something before it goes viral does
    not contain approval of the police."""
    post = FakePost(sentiment_label="positive",
                    text="Great work by the Surat police team, they responded "
                         "within ten minutes and handled it very professionally")
    assert emerging._claim_check(post) == "praise"


def test_a_reel_caption_asserts_nothing():
    """The real regression: this reel sat at the top of the queue scoring 82/100
    on 1.9 million algorithmic views, with a three-word caption."""
    post = FakePost(text="મારો જીવ 💕🔐🧿 . . . #instagram #instagood #india #viral",
                    hashtags=["instagram", "instagood", "india", "viral"],
                    engagement={"views": 1_891_768, "likes": 0,
                                "shares": 0, "comments": 0})
    assert emerging._claim_check(post) == "no substantive text"


def test_a_hashtag_wall_is_not_a_report():
    post = FakePost(text="new video out now watch full reel link in bio "
                         "#surat #rajkot #gujarat #viral #trending #reels "
                         "#explore #foryou #instagood #love #india #follow",
                    hashtags=["surat", "rajkot", "gujarat", "viral", "trending",
                              "reels", "explore", "foryou", "instagood", "love",
                              "india", "follow"])
    assert emerging._claim_check(post) == "hashtag-led caption"


def test_digits_and_emoji_are_not_words():
    """"₹100 !!! 🔥🔥" is nine characters of nothing to check."""
    assert emerging._body_words("₹100 !!! 🔥🔥 2026 #surat") == []


def test_indic_script_counts_as_words():
    """The claim gate must not quietly exclude every Gujarati post by failing to
    recognise its script as words."""
    words = emerging._body_words("સુરત સિવિલ હોસ્પિટલમાં ડોક્ટરનું મોત થયું છે")
    assert len(words) >= 6


# ── the established-channel gate ────────────────────────────────────────────

def test_a_verified_account_corroborates_rather_than_rumours():
    assert emerging._is_established(FakePost(author_verified=True)) is True


def test_a_configured_seed_desk_is_an_established_channel(monkeypatch):
    """Official desks arrive from the Telegram adapter with no follower count,
    so the follower test alone let a party's own press releases into the queue."""
    monkeypatch.setattr(emerging, "_seed_handles",
                        lambda: frozenset({"aapgujaratofficial"}))
    post = FakePost(author_handle="AAPGujaratOfficial", author_followers=0)
    assert emerging._is_established(post) is True
    assert emerging._is_established(FakePost(author_handle="a_citizen",
                                             author_followers=0)) is False


# ── scoring ─────────────────────────────────────────────────────────────────

def test_views_alone_cannot_reach_the_top_of_the_queue():
    """Views are the platform's decision, not a person's. A million of them are
    capped at a tenth of the score; a genuinely alarming claim outranks them."""
    viral_but_empty = FakePost(concern_score=28.0,
                               engagement={"views": 1_891_768, "likes": 0,
                                           "shares": 0, "comments": 0})
    alarming_claim = FakePost(concern_score=62.0, intent="rumor",
                              engagement={"views": 40})
    assert emerging._priority_score(alarming_claim)[0] > emerging._priority_score(viral_but_empty)[0]


def test_propagation_ignores_views_entirely():
    assert emerging._propagation(FakePost(engagement={"views": 5_000_000})) == 0
    assert emerging._propagation(
        FakePost(engagement={"likes": 10, "shares": 5, "comments": 3})) == 31


def test_rumour_phrasing_lifts_priority_over_an_identical_report():
    """`intent == "rumor"` means the lexicon matched the phrasing rumours are
    built from — the strongest single signal available that a post is a rumour
    rather than a report, so it has to move the ranking."""
    report = FakePost(concern_score=50.0, intent="informational")
    rumour = FakePost(concern_score=50.0, intent="rumor")
    assert emerging._priority_score(rumour)[0] > emerging._priority_score(report)[0]


@pytest.mark.parametrize("post", [
    FakePost(concern_score=100.0, intent="rumor",
             engagement={"likes": 10_000, "shares": 9_000, "comments": 5_000,
                         "views": 10_000_000}),
    FakePost(concern_score=0.0, intent="informational"),
])
def test_priority_stays_inside_its_stated_range(post):
    score, _, _ = emerging._priority_score(post)
    assert 0 <= score <= 100
    assert not math.isnan(score)
