# -*- coding: utf-8 -*-
"""Profile reads for the platforms that no longer answer a logged-out request.

Instagram, X, TikTok and Threads all serve a client-rendered shell to anyone
who is not signed in: byte-for-byte the same page for a real handle and an
invented one. Sherlock's manifest works around that with third-party mirrors
(`imginn.com` for Instagram, a nitter instance for X) — both of which are now
dead or Cloudflare-walled, which is exactly why a real Instagram handle came
back as "not found".

Rather than guessing, this module uses what the console already has:

  Instagram   the crawler's own logged-in instagrapi session, the same one
              collection uses (app/crawlers/instagrapi_ig.py)
  X           the crawler's twikit session, else a public read-only mirror

The collector instances are taken from the crawler registry, so a lookup rides
whatever session collection has already authenticated instead of logging in
again — a second login from the same IP is what gets an Instagram account
challenged.

When no session is available the answer is "blocked", never "not found", and
the note says which command restores it. An officer being told an account does
not exist, when the truth is that nobody checked, is the one outcome this
module exists to prevent.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# A revoked session fails the same way every time, and each attempt costs a
# real login round-trip against a platform that counts them. So a failure is
# remembered for a while and the reason is reused verbatim.
_COOLDOWN_SECONDS = 600.0
_failures: dict[str, tuple[float, str]] = {}


def _cooling(key: str) -> str:
    hit = _failures.get(key)
    if hit and time.monotonic() - hit[0] < _COOLDOWN_SECONDS:
        return hit[1]
    return ""


def _note_failure(key: str, reason: str) -> str:
    _failures[key] = (time.monotonic(), reason)
    return reason


def _reset(key: str) -> None:
    _failures.pop(key, None)


# ── Instagram, through the crawler's instagrapi session ───────────────────

def _instagrapi_collector():
    """The registry's own instance, so its authenticated client is reused."""
    from app.crawlers.registry import instagram_session_collector
    return instagram_session_collector()


def _read_instagram_sync(username: str) -> dict:
    from app.crawlers.instagrapi_ig import _lookup

    collector = _instagrapi_collector()
    if collector is None or not collector.is_configured():
        raise RuntimeError(
            "no Instagram session configured — set IG_SESSIONID in backend/.env "
            "or run `python -m app.crawlers.instagrapi_login`")
    client = collector._login_sync()          # cached on the collector instance
    info = _lookup(client, username)
    return {
        "handle": getattr(info, "username", "") or username,
        "display_name": getattr(info, "full_name", "") or "",
        "bio": getattr(info, "biography", "") or "",
        "avatar": str(getattr(info, "profile_pic_url_hd", "")
                      or getattr(info, "profile_pic_url", "") or ""),
        "followers": int(getattr(info, "follower_count", 0) or 0),
        "verified": bool(getattr(info, "is_verified", False)),
        "link": str(getattr(info, "external_url", "") or ""),
        "extra": {
            "private": bool(getattr(info, "is_private", False)),
            "posts": int(getattr(info, "media_count", 0) or 0),
            "user_id": str(getattr(info, "pk", "") or ""),
        },
    }


async def instagram_profile(username: str) -> tuple[dict | None, str]:
    """(profile, reason). `profile` is None when the session could not read it.

    instagrapi is synchronous and its client sleeps between private-API calls,
    so the whole read happens on a worker thread.
    """
    cooling = _cooling("instagram")
    if cooling:
        return None, cooling
    try:
        profile = await asyncio.to_thread(_read_instagram_sync, username)
        _reset("instagram")
        return profile, ""
    except Exception as exc:                      # noqa: BLE001
        text = str(exc)
        low = text.lower()
        if "not found" in low or "user_not_found" in low or "404" in low:
            # A session that works and says the handle does not exist is a real
            # answer, not a failure — and it must not poison the cooldown.
            _reset("instagram")
            return None, "not_found"
        log.info("instagram session lookup failed for %s: %s", username, text[:200])
        return None, _note_failure("instagram", _readable(text))


def _readable(text: str) -> str:
    low = text.lower()
    if "login_required" in low or "logged out" in low or "revoked" in low:
        return ("the Instagram session was revoked — run "
                "`python -m app.crawlers.instagrapi_login` to restore it")
    if "challenge" in low or "checkpoint" in low:
        return ("Instagram is challenging the session — run "
                "`python -m app.crawlers.instagrapi_login` and answer the code")
    if "no instagram session" in low:
        return text
    if "please wait" in low or "429" in low or "rate" in low:
        return "Instagram is rate-limiting this session — try again later"
    return f"Instagram session unavailable ({text[:120]})"


# ── X, through the crawler's twikit session ───────────────────────────────

async def x_session_profile(username: str) -> tuple[dict | None, str]:
    cooling = _cooling("x")
    if cooling:
        return None, cooling
    try:
        from app.crawlers.registry import x_session_collector
        collector = x_session_collector()
        if collector is None or not collector.is_configured():
            return None, _note_failure("x", "no X session configured (x_cookies.json)")
        client = await collector._login()
        user = await client.get_user_by_screen_name(username)
        if user is None:
            return None, "not_found"
        _reset("x")
        return {
            "handle": getattr(user, "screen_name", "") or username,
            "display_name": getattr(user, "name", "") or "",
            "bio": getattr(user, "description", "") or "",
            "avatar": (getattr(user, "profile_image_url", "") or "").replace("_normal", "_400x400"),
            "followers": getattr(user, "followers_count", None),
            "verified": bool(getattr(user, "verified", False)),
            "created_at": str(getattr(user, "created_at", "") or "")[:10],
            "location": getattr(user, "location", "") or "",
            "link": getattr(user, "url", "") or "",
            "extra": {"following": getattr(user, "following_count", None),
                      "tweets": getattr(user, "statuses_count", None)},
        }, ""
    except Exception as exc:                      # noqa: BLE001
        text = str(exc)
        if "not found" in text.lower() or "404" in text:
            return None, "not_found"
        log.info("twikit X lookup failed for %s: %s", username, text[:200])
        return None, _note_failure("x", f"X session unavailable ({text[:120]})")


# ── X, through a public read-only mirror ──────────────────────────────────

# Open-source relays of X's own public profile data. They exist because X
# closed the logged-out profile page; sherlock's manifest reaches for the same
# kind of thing (a nitter instance) and that one is dead, so these are tried in
# order and the first that answers wins.
_X_MIRRORS = ("https://api.fxtwitter.com/{u}", "https://api.vxtwitter.com/{u}")


def _from_fx(body: dict) -> dict | None:
    user = body.get("user")
    if not isinstance(user, dict):
        return None
    website = user.get("website") or {}
    return {
        "handle": user.get("screen_name") or "",
        "display_name": user.get("name") or "",
        "bio": user.get("description") or "",
        "avatar": (user.get("avatar_url") or "").replace("_normal", "_400x400"),
        "followers": user.get("followers"),
        "verified": bool((user.get("verification") or {}).get("verified", False)),
        "created_at": _twitter_date(user.get("joined") or ""),
        "location": user.get("location") or "",
        "link": (website.get("url") if isinstance(website, dict) else "") or "",
        "extra": {"following": user.get("following"), "tweets": user.get("tweets"),
                  "protected": bool(user.get("protected"))},
    }


def _from_vx(body: dict) -> dict | None:
    if not body.get("screen_name"):
        return None
    return {
        "handle": body.get("screen_name") or "",
        "display_name": body.get("name") or "",
        "bio": body.get("description") or "",
        "avatar": (body.get("profile_image_url") or "").replace("_normal", "_400x400"),
        "followers": body.get("followers_count"),
        "verified": False,                        # vx does not report it
        "created_at": _twitter_date(body.get("created_at") or ""),
        "location": body.get("location") or "",
        "link": "",
        "extra": {"following": body.get("following_count"),
                  "tweets": body.get("tweet_count"),
                  "protected": bool(body.get("protected"))},
    }


def _twitter_date(raw: str) -> str:
    """"Tue Nov 18 21:28:10 +0000 2008" -> "2008-11-18"."""
    try:
        from datetime import datetime
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%d")
    except Exception:                             # noqa: BLE001
        return ""


async def x_mirror_profile(client: httpx.AsyncClient,
                           username: str) -> tuple[dict | None, str]:
    """(profile, reason). reason == "not_found" is a real answer from a mirror."""
    if not settings.X_PUBLIC_MIRRORS:
        return None, "X public mirrors disabled"
    saw_404 = False
    for template in _X_MIRRORS:
        try:
            r = await client.get(template.format(u=username),
                                 headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:                  # noqa: BLE001
            log.debug("x mirror %s failed: %s", template, exc)
            continue
        if r.status_code == 404:
            saw_404 = True
            continue
        if r.status_code != 200:
            continue
        try:
            body = r.json()
        except Exception:                         # noqa: BLE001
            continue
        profile = _from_fx(body) if "user" in body else _from_vx(body)
        if profile and profile["handle"]:
            return profile, ""
    if saw_404:
        return None, "not_found"
    return None, "no X mirror answered"
