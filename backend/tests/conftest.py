"""Shared test fixtures.

The one thing here is roster isolation, and it is autouse for a reason. The
crawlers keep the accounts they discover in a real file next to the database
(crawlers/roster.py). A test that exercises a collector would otherwise read
the developer's own roster — hundreds of live Instagram handles on one machine,
none on a fresh clone — so the same test would drive a stub client through a
different set of accounts on every box, and could *write* to that file as a
side effect of running the suite.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import pytest

from app.crawlers import roster


@pytest.fixture(autouse=True)
def isolated_roster(tmp_path, monkeypatch):
    """Every test gets an empty roster of its own."""
    monkeypatch.setattr(roster, "ROSTER_FILE", tmp_path / "discovered_accounts.json")
    return roster.ROSTER_FILE


@pytest.fixture(autouse=True)
def no_live_instagram(monkeypatch):
    """No test reaches Instagram's signed-out routes for real.

    The Instagram adapter falls back to them whenever its session is refused,
    which is precisely the state several tests set up — so without this the
    suite quietly starts making live calls to instagram.com, and its results
    depend on Instagram's rate limiter. A test that wants the fallback stubs
    these itself.
    """
    from app.crawlers import instagram_public

    def refuse(*_args, **_kwargs):
        raise AssertionError(
            "a test reached Instagram's live public routes — stub "
            "instagram_public.hashtag_medias for this test")

    for name in ("hashtag_medias", "profile", "user_medias", "account_medias",
                 "_session"):
        monkeypatch.setattr(instagram_public, name, refuse)
