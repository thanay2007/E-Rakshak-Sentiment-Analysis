"""Coordinated-campaign detection: what counts as a campaign, and what doesn't.

Every test here exists because the detector once got the case wrong on live
data, and the wrong answers were not near-misses — they were the Surat City
Police being reported as running a "coordinated whitewash / paid praise"
operation because its Instagram, Facebook and X accounts had each carried the
same arrest notice.

The three things that were broken, and are now asserted:

  1. handle strings were treated as identities, so @amdavadamc (Instagram) and
     @AmdavadAMC (X) — one municipal corporation — satisfied a "3 accounts"
     rule between them
  2. nothing distinguished an account with half a million followers and a
     decade of history from a two-week-old egg, so a press release syndicated
     between official desks scored exactly like an astroturf roster
  3. duplication alone cleared the bar; there was no requirement for any
     evidence that the posting was organised, and a 0.30 floor meant everything
     that clustered got reported

And the fourth, which matters just as much: the genuine astroturf cluster in the
same corpus — eight throwaway accounts posting identical 50-word political copy
inside twenty minutes — must survive all of the above.

Run:  cd backend && python -m pytest tests/test_pr_campaigns.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.osint import pr_analysis
from app.osint.pr_analysis import MIN_CONFIDENCE, actor_key, detect_pr_campaigns


class FakePost:
    """Just the columns detect_pr_campaigns selects."""

    def __init__(self, *, handle, text, minutes_ago=0, platform="X", followers=40,
                 age_days=200, verified=False, label="negative", concern=55.0,
                 name="", amplified=False, location="Surat"):
        now = datetime(2026, 8, 16, 12, 0, 0)
        self.id = f"{handle}-{minutes_ago}-{abs(hash(text)) % 10000}"
        self.platform = platform
        self.author_handle = handle
        self.author_name = name
        self.author_followers = followers
        self.author_account_age_days = age_days
        self.author_verified = verified
        self.text = text
        self.translation = ""
        self.sentiment_label = label
        self.concern_score = concern
        self.engagement = {"shares": 3, "views": 100}
        self.hashtags = []
        self.location = location
        self.is_amplified = amplified
        self.created_at = now - timedelta(minutes=minutes_ago)


ASTROTURF_COPY = (
    "In 1942 during the tumultuous period Shri Guruji wrote a letter to Vasant "
    "Rao of Surat emphasising that the organisation must remain disciplined and "
    "that every worker should dedicate himself to the nation before anything "
    "else, a message that still guides the movement today and deserves to be "
    "remembered by every citizen of this country without exception at all"
)

PRESS_RELEASE = (
    "Surat Sachin GIDC police commendable action in the kidnapping case "
    "registered at Radhanagar police station the accused was traced and "
    "arrested within twenty four hours after technical surveillance by the team "
    "and the minor was safely recovered and handed back to the family members"
)


def run(posts, **kw):
    """Drive the detector against a fixed post list instead of the database."""
    def fake_scope():
        class _S:
            def exec(self, *_a, **_k):
                class _R:
                    def all(_self):
                        return posts
                return _R()

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False
        return _S()

    original = pr_analysis.session_scope
    pr_analysis.session_scope = fake_scope
    try:
        return detect_pr_campaigns(**kw)
    finally:
        pr_analysis.session_scope = original


# ── identity folding ───────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("amdavadamc", "AmdavadAMC"),
    ("srfdcl_", "SRFDCL"),
    ("Surat_City_Police", "suratcitypolice"),
])
def test_case_and_punctuation_do_not_make_a_second_account(a, b):
    assert actor_key(a) == actor_key(b)


def test_one_organisation_on_three_platforms_is_not_three_accounts():
    """The Surat police case: same notice, three of its own handles."""
    posts = [
        FakePost(handle="suratcitypolice", platform="Instagram", text=PRESS_RELEASE,
                 followers=446163, label="positive"),
        FakePost(handle="SuratCityPolice", platform="Facebook", text=PRESS_RELEASE,
                 minutes_ago=5, followers=458000, label="positive"),
        FakePost(handle="Surat_City_Police", platform="X", text=PRESS_RELEASE,
                 minutes_ago=9, followers=84609, label="positive"),
    ]
    report = run(posts, hours=48, min_accounts=3)
    assert report["campaigns_found"] == 0, (
        "one police force posting to its own accounts is not a campaign")


# ── the authenticity gate ──────────────────────────────────────────────────

def test_established_desks_syndicating_a_release_are_reported_as_syndication():
    """Three genuinely different official bodies carrying the same notice."""
    posts = [
        FakePost(handle="suratcitypolice", platform="Instagram", text=PRESS_RELEASE,
                 followers=446163, label="positive"),
        FakePost(handle="CP_SuratCity", platform="X", text=PRESS_RELEASE,
                 minutes_ago=4, followers=84609, age_days=3793, label="positive"),
        FakePost(handle="GujaratFirstNews", platform="X", text=PRESS_RELEASE,
                 minutes_ago=7, followers=17850, verified=True, label="positive"),
    ]
    report = run(posts, hours=48, min_accounts=3)
    assert report["campaigns_found"] == 0
    assert report["syndication_ignored"] == 1, "it must still be visible, not dropped"
    why = report["syndication"][0]["why"].lower()
    assert "established" in why or "one organisation" in why


def test_a_long_lived_account_with_a_real_audience_is_not_roster_material():
    a = pr_analysis._Actor("x")
    a.followers, a.age_days = 84_609, 3_793
    assert a.established(set())[0]

    egg = pr_analysis._Actor("y")
    egg.followers, egg.age_days = 9, 1_460
    assert not egg.established(set())[0]


def test_seed_desks_count_as_official_however_small():
    actor = pr_analysis._Actor("vadodaracitypolice")
    actor.followers, actor.age_days = 300, 40
    assert not actor.established(set())[0]
    assert actor.established({"vadodaracitypolice"})[0]


# ── the corroboration gate ─────────────────────────────────────────────────

def test_shared_wording_alone_is_not_a_campaign():
    """Three unremarkable accounts, same phrasing, spread over two days.

    No burst, no bot signals, no cross-platform distribution — this is people
    saying the same thing, which is what a shared phrase looks like.
    """
    posts = [
        FakePost(handle="rajesh_patel_ahd", text=ASTROTURF_COPY, minutes_ago=0,
                 followers=1200, age_days=1500),
        FakePost(handle="meena_shah22", text=ASTROTURF_COPY, minutes_ago=900,
                 followers=980, age_days=1200),
        FakePost(handle="kiran_desai", text=ASTROTURF_COPY, minutes_ago=2600,
                 followers=1500, age_days=2000),
    ]
    report = run(posts, hours=72, min_accounts=3)
    assert report["campaigns_found"] == 0
    assert report["weak_clusters_ignored"] == 1


def test_real_astroturf_still_gets_caught():
    """The live-corpus case the whole filter has to survive: throwaway accounts,
    identical long copy, all inside twenty minutes."""
    handles = ["BabluPr25103178", "GadgilKekr88276", "rampatidar96", "jeta1689",
               "ArGaurav2", "Anubhav4tiwari"]
    posts = [
        FakePost(handle=h, text=ASTROTURF_COPY, minutes_ago=i * 3,
                 followers=20 + i, age_days=300, label="positive", concern=30.0)
        for i, h in enumerate(handles)
    ]
    report = run(posts, hours=48, min_accounts=3)
    assert report["campaigns_found"] == 1
    campaign = report["campaigns"][0]
    assert campaign["account_count"] == len(handles)
    assert campaign["confidence"] >= MIN_CONFIDENCE
    assert any("synchronized" in w or "one hour" in w for w in campaign["why"])


def test_nothing_below_the_confidence_floor_is_reported():
    posts = [
        FakePost(handle=f"user_{i}", text=ASTROTURF_COPY, minutes_ago=i * 700,
                 followers=5000, age_days=90)
        for i in range(3)
    ]
    report = run(posts, hours=72, min_accounts=3)
    assert all(c["confidence"] >= MIN_CONFIDENCE for c in report["campaigns"])


# ── labelling ──────────────────────────────────────────────────────────────

def test_no_type_label_asserts_that_anyone_was_paid():
    """Nothing measured here establishes payment, so nothing may claim it."""
    for label in pr_analysis._TYPE_LABEL.values():
        assert "paid" not in label.lower()
