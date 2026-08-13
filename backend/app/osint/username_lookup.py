# -*- coding: utf-8 -*-
"""Cross-platform username lookup — official APIs first, URL probes last.

A bare profile-URL probe answers one question badly: "did this host return 200?"
It cannot tell a real account from a placeholder page, a soft-404 from a hit, or
a squatted handle from the person actually being investigated. So wherever a
platform publishes a profile API, this module calls it and reads the account:

    GitHub     REST /users/{u}              name, bio, avatar, followers, created
    Reddit     OAuth /user/{u}/about        (falls back to public about.json)
    X          API v2 /users/by/username    name, bio, avatar, metrics, created
    YouTube    Data v3 channels?forHandle   title, description, subs, created
    Instagram  public web_profile_info      name, bio, avatar, followers
    Telegram   t.me OpenGraph card          title, description, avatar

Only platforms with no public profile API left (Facebook, TikTok, Threads, …)
fall back to the old probe, and those are labelled `source: "probe"` in the
response so the UI can say which findings are read and which are inferred.

Having real profiles instead of booleans is what makes the second half possible:
**correlation**. Two accounts are tied to one person by evidence, not by sharing
a string — the same display name, the same profile photo (compared by perceptual
hash, so a re-encode or a resize still matches), overlapping bio vocabulary, the
same declared location or link. That scoring also runs over *handle variants*
and platform user-search results, which is how `desh_sachai_4471` surfaces
`desh_sachai` and `deshsachai_official` as probably-the-same-person, each with
the reasons spelled out rather than a bare number.

Every request is a public, unauthenticated-or-officially-keyed GET. Nothing logs
in as the target, nothing scrapes a rendered page, and a failure anywhere
degrades that one platform to "unknown" instead of failing the run.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from collections import Counter
from typing import Awaitable, Callable

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_VALID = re.compile(r"^[A-Za-z0-9._-]{2,40}$")

# Probe-only catalogue: (site, url template, category, mode, marker).
#
# `mode` records what a probe can actually prove on that host, measured rather
# than assumed:
#   "status" — a missing handle really answers 404, so 200 means present.
#   "og"     — the host answers 200 for everything, but the OpenGraph title of a
#              real profile differs from `marker`, its generic site-wide title.
#   "js"     — the page is rendered client-side and the HTML is byte-identical
#              for a real and an invented handle. No request is made at all;
#              reporting "found" here would be inventing a finding.
_PROBE_SITES: list[tuple[str, str, str, str, str]] = [
    ("Snapchat", "https://www.snapchat.com/add/{u}", "social", "status", ""),
    ("VK", "https://vk.com/{u}", "social", "status", ""),
    ("SoundCloud", "https://soundcloud.com/{u}", "audio", "status", ""),
    ("Medium", "https://medium.com/@{u}", "blog", "status", ""),
    ("Linktree", "https://linktr.ee/{u}", "link-hub", "status", ""),
    ("Mastodon (mastodon.social)", "https://mastodon.social/@{u}", "social", "status", ""),
    ("Twitch", "https://www.twitch.tv/{u}", "streaming", "og", "Twitch"),
    ("Facebook", "https://www.facebook.com/{u}", "social", "js", ""),
    ("TikTok", "https://www.tiktok.com/@{u}", "social", "js", ""),
    ("Threads", "https://www.threads.net/@{u}", "social", "js", ""),
    ("Pinterest", "https://www.pinterest.com/{u}/", "social", "js", ""),
    ("Dailymotion", "https://www.dailymotion.com/{u}", "video", "js", ""),
]

_OG = {
    "title": re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']{0,200})', re.I),
    "desc": re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{0,400})', re.I),
    "image": re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']{0,500})', re.I),
}

# Words that co-occur in every other bio and therefore prove nothing.
_STOP = {
    "the", "and", "for", "with", "you", "your", "our", "all", "not", "from",
    "this", "that", "are", "was", "will", "can", "has", "have", "his", "her",
    "official", "account", "page", "profile", "follow", "followers", "here",
    "life", "love", "world", "india", "new", "now", "just", "more", "about",
    # Platform boilerplate. Every OpenGraph card says the platform's own name
    # and invites you to join it, so these would "corroborate" any two pages.
    "instagram", "facebook", "twitter", "telegram", "youtube", "tiktok",
    "snapchat", "twitch", "reddit", "github", "pinterest", "soundcloud",
    "threads", "medium", "linktree", "dailymotion", "mastodon", "share",
    "join", "watch", "listen", "photos", "videos", "video", "channel",
    "community", "chat", "contact", "right", "away", "check", "audio",
    "create", "lets", "see", "like", "app", "free", "online", "latest",
}

# Avatar URLs that are the platform's placeholder, not a person's photo. Two
# accounts "sharing" a default egg is not evidence of anything.
_DEFAULT_AVATAR = re.compile(
    r"(user-default|default[-_]?(profile|avatar|picture|user)|/defaults?/|"
    r"anonymous|placeholder|no[-_]?avatar|gravatar\.com/avatar/0{8})", re.I)


def validate(username: str) -> str | None:
    u = (username or "").strip().lstrip("@")
    return u if _VALID.match(u) else None


def _blank(site: str, category: str, url: str) -> dict:
    """Every result carries the same keys, so the UI never branches on presence."""
    return {
        "site": site, "category": category, "url": url,
        "status": "unknown", "http": None, "source": "probe",
        "handle": "", "display_name": "", "bio": "", "avatar": "",
        "followers": None, "created_at": "", "verified": False,
        "location": "", "link": "", "extra": {},
    }


# ── text helpers used by correlation ──────────────────────────────────────

def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _tokens(s: str) -> set[str]:
    words = re.findall(r"[a-z0-9']{3,}", (s or "").lower())
    return {w for w in words if w not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _hamming(a: str, b: str) -> int:
    """Bit distance between two hex dhashes; 999 when either is missing."""
    if not a or not b:
        return 999
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 999


def _usable_hash(h: str) -> bool:
    """Reject degenerate hashes before they become false evidence.

    A near-uniform image — a blank square, a solid-colour placeholder, a failed
    render — hashes to almost all zeros or almost all ones, and any two such
    images look identical to a perceptual hash. Treating that as "same photo"
    is how an avatar comparison manufactures matches out of missing data.
    """
    if not h:
        return False
    try:
        bits = bin(int(h, 16)).count("1")
    except ValueError:
        return False
    return 4 <= bits <= 60


def _handle_tokens(u: str) -> set[str]:
    """The handle's own words — evidence that a bio contains them is circular."""
    parts = {p for p in re.split(r"[^a-z0-9]+", (u or "").lower()) if len(p) >= 3}
    return parts | {_core(u), re.sub(r"[^a-z0-9]+", "", (u or "").lower())}


def _core(handle: str) -> str:
    """Handle reduced to its identity-bearing part: no separators, no trailing digits."""
    h = re.sub(r"[^a-z0-9]+", "", (handle or "").lower())
    return re.sub(r"\d+$", "", h) or h


# ── platform resolvers (official / public APIs) ───────────────────────────

async def _github(client: httpx.AsyncClient, u: str) -> dict:
    out = _blank("GitHub", "dev", f"https://github.com/{u}")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": _UA}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    try:
        r = await client.get(f"https://api.github.com/users/{u}", headers=headers)
        out["http"] = r.status_code
        out["source"] = "api"
        if r.status_code == 404:
            out["status"] = "not_found"
            return out
        if r.status_code in (403, 429):
            out["status"] = "blocked"
            out["extra"]["note"] = "GitHub API rate limit — set GITHUB_TOKEN to lift it"
            return out
        if r.status_code != 200:
            return out
        d = r.json()
        out.update(
            status="found", handle=d.get("login") or u,
            url=d.get("html_url") or out["url"],
            display_name=d.get("name") or "", bio=d.get("bio") or "",
            avatar=d.get("avatar_url") or "", followers=d.get("followers"),
            created_at=(d.get("created_at") or "")[:10],
            location=d.get("location") or "", link=d.get("blog") or "",
        )
        out["extra"] = {"public_repos": d.get("public_repos"),
                        "company": d.get("company") or ""}
    except Exception as exc:                      # noqa: BLE001 — one dead API is not a failed run
        log.debug("github lookup failed for %s: %s", u, exc)
    return out


async def _reddit_token(client: httpx.AsyncClient) -> str:
    if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
        return ""
    try:
        r = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET),
            headers={"User-Agent": settings.REDDIT_USER_AGENT},
        )
        if r.status_code == 200:
            return r.json().get("access_token", "")
    except Exception as exc:                      # noqa: BLE001
        log.debug("reddit token failed: %s", exc)
    return ""


async def _reddit(client: httpx.AsyncClient, u: str, token: str = "") -> dict:
    out = _blank("Reddit", "social", f"https://www.reddit.com/user/{u}")
    if token:
        url = f"https://oauth.reddit.com/user/{u}/about"
        headers = {"Authorization": f"Bearer {token}",
                   "User-Agent": settings.REDDIT_USER_AGENT}
    else:
        url = f"https://www.reddit.com/user/{u}/about.json?raw_json=1"
        headers = {"User-Agent": settings.REDDIT_USER_AGENT}
    try:
        r = await client.get(url, headers=headers)
        out["http"] = r.status_code
        out["source"] = "api"
        if r.status_code in (403, 404):
            # Reddit answers both "no such user" and "suspended" here; 404 is a
            # miss, 403 usually means the account exists but is shadow-gone.
            out["status"] = "not_found" if r.status_code == 404 else "blocked"
            return out
        if r.status_code == 429:
            out["status"] = "blocked"
            return out
        if r.status_code != 200:
            return out
        d = (r.json() or {}).get("data") or {}
        if not d:
            out["status"] = "not_found"
            return out
        created = d.get("created_utc")
        out.update(
            status="found", handle=d.get("name") or u,
            display_name=d.get("subreddit", {}).get("title") or d.get("name") or "",
            bio=d.get("subreddit", {}).get("public_description") or "",
            avatar=(d.get("icon_img") or "").split("?")[0],
            followers=d.get("subreddit", {}).get("subscribers"),
            verified=bool(d.get("verified")),
            created_at=time.strftime("%Y-%m-%d", time.gmtime(created)) if created else "",
        )
        out["extra"] = {"total_karma": d.get("total_karma"),
                        "link_karma": d.get("link_karma"),
                        "comment_karma": d.get("comment_karma")}
    except Exception as exc:                      # noqa: BLE001
        log.debug("reddit lookup failed for %s: %s", u, exc)
    return out


async def _x(client: httpx.AsyncClient, u: str) -> dict:
    out = _blank("X / Twitter", "social", f"https://x.com/{u}")
    if not settings.X_BEARER_TOKEN:
        out["extra"]["note"] = "no X_BEARER_TOKEN — set one for a real profile read"
        return out
    try:
        r = await client.get(
            f"https://api.twitter.com/2/users/by/username/{u}",
            params={"user.fields": "description,profile_image_url,public_metrics,"
                                   "created_at,verified,location,url"},
            headers={"Authorization": f"Bearer {settings.X_BEARER_TOKEN}"},
        )
        out["http"] = r.status_code
        out["source"] = "api"
        if r.status_code == 429:
            out["status"] = "blocked"
            out["extra"]["note"] = "X API rate limit"
            return out
        if r.status_code != 200:
            return out
        body = r.json() or {}
        d = body.get("data")
        if not d:
            out["status"] = "not_found"
            return out
        metrics = d.get("public_metrics") or {}
        out.update(
            status="found", handle=d.get("username") or u,
            display_name=d.get("name") or "", bio=d.get("description") or "",
            # _normal is the 48px thumbnail; _400x400 is the same image bigger,
            # which makes the perceptual hash comparable with other platforms'.
            avatar=(d.get("profile_image_url") or "").replace("_normal", "_400x400"),
            followers=metrics.get("followers_count"),
            verified=bool(d.get("verified")),
            created_at=(d.get("created_at") or "")[:10],
            location=d.get("location") or "", link=d.get("url") or "",
        )
        out["extra"] = {"following": metrics.get("following_count"),
                        "tweets": metrics.get("tweet_count")}
    except Exception as exc:                      # noqa: BLE001
        log.debug("x lookup failed for %s: %s", u, exc)
    return out


async def _youtube(client: httpx.AsyncClient, u: str) -> dict:
    out = _blank("YouTube", "video", f"https://www.youtube.com/@{u}")
    if not settings.YOUTUBE_API_KEY:
        out["extra"]["note"] = "no YOUTUBE_API_KEY — set one for a real channel read"
        return out
    try:
        # channels.list costs 1 quota unit; search.list would cost 100, which is
        # why handles are resolved directly and never searched for.
        r = await client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet,statistics", "forHandle": f"@{u}",
                    "key": settings.YOUTUBE_API_KEY},
        )
        out["http"] = r.status_code
        out["source"] = "api"
        if r.status_code == 403:
            out["status"] = "blocked"
            out["extra"]["note"] = "YouTube quota exhausted"
            return out
        if r.status_code != 200:
            return out
        items = (r.json() or {}).get("items") or []
        if not items:
            out["status"] = "not_found"
            return out
        it = items[0]
        sn = it.get("snippet") or {}
        st = it.get("statistics") or {}
        thumbs = (sn.get("thumbnails") or {})
        out.update(
            status="found", handle=(sn.get("customUrl") or f"@{u}").lstrip("@"),
            url=f"https://www.youtube.com/channel/{it.get('id')}",
            display_name=sn.get("title") or "", bio=sn.get("description") or "",
            avatar=(thumbs.get("high") or thumbs.get("default") or {}).get("url", ""),
            followers=int(st["subscriberCount"]) if st.get("subscriberCount") else None,
            created_at=(sn.get("publishedAt") or "")[:10],
            location=sn.get("country") or "",
        )
        out["extra"] = {"videos": st.get("videoCount"), "views": st.get("viewCount")}
    except Exception as exc:                      # noqa: BLE001
        log.debug("youtube lookup failed for %s: %s", u, exc)
    return out


async def _instagram(client: httpx.AsyncClient, u: str) -> dict:
    out = _blank("Instagram", "social", f"https://www.instagram.com/{u}/")
    try:
        # The endpoint Instagram's own web client calls for a public profile.
        # It is frequently gated to logged-in sessions; a 401 there is a
        # "blocked", not a "no such account".
        r = await client.get(
            "https://www.instagram.com/api/v1/users/web_profile_info/",
            params={"username": u},
            headers={"User-Agent": _UA, "X-IG-App-ID": "936619743392459",
                     "Accept": "application/json"},
        )
        out["http"] = r.status_code
        out["source"] = "api"
        if r.status_code == 404:
            out["status"] = "not_found"
            return out
        if r.status_code in (401, 403, 429):
            out["status"] = "blocked"
            out["extra"]["note"] = "Instagram requires a session for profile reads"
            return out
        if r.status_code != 200:
            return out
        d = ((r.json() or {}).get("data") or {}).get("user")
        if not d:
            out["status"] = "not_found"
            return out
        out.update(
            status="found", handle=d.get("username") or u,
            display_name=d.get("full_name") or "", bio=d.get("biography") or "",
            avatar=d.get("profile_pic_url_hd") or d.get("profile_pic_url") or "",
            followers=(d.get("edge_followed_by") or {}).get("count"),
            verified=bool(d.get("is_verified")),
            link=d.get("external_url") or "",
        )
        out["extra"] = {"private": bool(d.get("is_private")),
                        "posts": (d.get("edge_owner_to_timeline_media") or {}).get("count")}
    except Exception as exc:                      # noqa: BLE001
        log.debug("instagram lookup failed for %s: %s", u, exc)
    return out


async def _telegram(client: httpx.AsyncClient, u: str) -> dict:
    out = _blank("Telegram", "messaging", f"https://t.me/{u}")
    try:
        r = await client.get(f"https://t.me/{u}", headers={"User-Agent": _UA},
                             follow_redirects=True)
        out["http"] = r.status_code
        out["source"] = "api"
        if r.status_code != 200:
            return out
        html = r.text
        if "tgme_page_title" not in html:
            out["status"] = "not_found"
            return out
        title = _OG["title"].search(html)
        desc = _OG["desc"].search(html)
        image = _OG["image"].search(html)
        name = (title.group(1) if title else "").replace("Telegram: Contact ", "").strip()
        out.update(status="found", handle=u, display_name=name,
                   bio=(desc.group(1) if desc else "").strip(),
                   avatar=image.group(1) if image else "")
        # Channels and groups render a subscriber counter; a personal account does not.
        subs = re.search(r'([\d\s,]+)\s+(?:subscribers|members)', html)
        if subs:
            digits = re.sub(r"\D", "", subs.group(1))
            out["followers"] = int(digits) if digits else None
            out["extra"]["kind"] = "channel/group"
        else:
            out["extra"]["kind"] = "personal"
    except Exception as exc:                      # noqa: BLE001
        log.debug("telegram lookup failed for %s: %s", u, exc)
    return out


async def _probe(client: httpx.AsyncClient, site: tuple, u: str) -> dict:
    """Unauthenticated profile-URL probe for platforms with no public API."""
    name, tmpl, category, mode, marker = site
    out = _blank(name, category, tmpl.format(u=u))

    if mode == "js":
        # Verified: this host serves the same client-rendered shell for a real
        # handle and an invented one. There is no request worth making — the
        # honest answer is "open it yourself", not a coin-flip 200.
        out["extra"]["note"] = "renders client-side — a URL probe cannot confirm it"
        return out

    try:
        r = await client.get(out["url"], follow_redirects=True,
                             headers={"User-Agent": _UA})
        out["http"] = r.status_code
        if r.status_code == 404:
            out["status"] = "not_found"
        elif r.status_code in (200, 301, 302):
            head = r.text[:200_000]
            title = _OG["title"].search(head)
            title_text = title.group(1).strip() if title else ""
            if mode == "og" and (not title_text
                                 or title_text.lower() == marker.lower()):
                # The site's generic title means the profile did not resolve.
                out["status"] = "not_found"
                return out
            out["status"] = "found"
            out["handle"] = u
            # OpenGraph is the only metadata a probe can honestly claim.
            desc = _OG["desc"].search(head)
            image = _OG["image"].search(head)
            if title_text:
                out["display_name"] = title_text[:120]
            if desc:
                out["bio"] = desc.group(1).strip()[:400]
            if image:
                out["avatar"] = image.group(1).strip()
        elif r.status_code in (403, 429):
            out["status"] = "blocked"
    except Exception as exc:                      # noqa: BLE001
        log.debug("probe %s failed for %s: %s", name, u, exc)
    return out


# ── avatar hashing (the strongest correlation signal available) ───────────

async def _avatar_hash(client: httpx.AsyncClient, url: str) -> str:
    """Perceptual hash of a profile photo, or "" when it cannot be read.

    Deliberately the same dhash the image-forensics tool uses, so a distance
    here means what it means there.
    """
    if not url:
        return ""
    try:
        r = await client.get(url, headers={"User-Agent": _UA}, follow_redirects=True)
        if r.status_code != 200 or len(r.content) > 8_000_000:
            return ""
        from PIL import Image

        from app.osint.image_analysis import _dhash
        img = Image.open(io.BytesIO(r.content))
        img.load()
        return _dhash(img)
    except Exception as exc:                      # noqa: BLE001
        log.debug("avatar hash failed for %s: %s", url[:120], exc)
        return ""


# ── identity + correlation ────────────────────────────────────────────────

def _identity(found: list[dict], handle: str = "") -> dict:
    """Consensus view of the person, built only from platforms that were read.

    Names coming from an API count double: a platform's own OpenGraph title is
    boilerplate ("torvalds - Twitch"), whereas `name` on a profile endpoint is
    what the account holder typed.
    """
    banned = _handle_tokens(handle)
    api_names: Counter[str] = Counter()
    probe_names: Counter[str] = Counter()
    for r in found:
        n = r["display_name"].strip()
        if n:
            (api_names if r["source"] == "api" else probe_names)[n] += 1
    # A profile endpoint's `name` is what the account holder typed. An
    # OpenGraph title is the platform's template ("torvalds - Twitch",
    # "Snapchat પર …") and would otherwise become the consensus identity.
    names = api_names or probe_names

    bio_tokens: set[str] = set()
    for r in found:
        bio_tokens |= _tokens(r["bio"])
    bio_tokens -= banned

    hashes = [r["avatar_hash"] for r in found
              if _usable_hash(r.get("avatar_hash", ""))]
    return {
        "display_name": names.most_common(1)[0][0] if names else "",
        "display_names": [n for n, _ in names.most_common(4)],
        "bio_tokens": bio_tokens,
        "avatar_hashes": hashes,
        "banned_tokens": banned,
        "locations": sorted({r["location"].strip() for r in found if r["location"].strip()}),
        "links": sorted({r["link"].strip() for r in found if r["link"].strip()}),
        "verified_on": [r["site"] for r in found if r["verified"]],
        "total_reach": sum(r["followers"] or 0 for r in found),
    }


def _score_against(profile: dict, ident: dict, *, handle_relation: str,
                   original: str) -> tuple[int, list[str]]:
    """Confidence 0-100 that `profile` belongs to the same person as `ident`.

    `ident` must never include `profile` itself — an account trivially matches
    its own photo and its own bio, and scoring it against a core it contributed
    to returns 100 for every hit, which is a number that means nothing.

    No single signal reaches the top band alone: a shared display name is common
    enough that it has to be corroborated by a photo, a bio or a link.
    """
    score = 0
    why: list[str] = []
    banned = ident.get("banned_tokens", set())

    if handle_relation == "same":
        score += 35
        why.append("handle is identical across platforms")
    elif handle_relation == "variant":
        score += 12
        why.append(f"handle is a close variant of “{original}”")

    # A "display name" that is just the handle (or the platform's own title
    # template) says nothing beyond what the handle already said.
    name_tokens = _tokens(profile.get("display_name", "")) - banned
    name = _norm_name(profile.get("display_name", ""))
    if name and name_tokens:
        for known in ident["display_names"]:
            k = _norm_name(known)
            if not k or not (_tokens(known) - banned):
                continue
            if name == k:
                score += 30
                why.append(f"display name matches “{known}”")
                break
            if _jaccard(name_tokens, _tokens(known) - banned) >= 0.5:
                score += 16
                why.append(f"display name overlaps “{known}”")
                break

    mine = profile.get("avatar_hash", "")
    if _usable_hash(mine):
        best = min((_hamming(mine, h) for h in ident["avatar_hashes"]), default=999)
        if best <= 6:
            score += 35
            why.append(f"profile photo is the same image (perceptual distance {best})")
        elif best <= 12:
            score += 16
            why.append(f"profile photo is visually similar (distance {best})")

    shared = (_tokens(profile.get("bio", "")) & ident["bio_tokens"]) - banned
    if len(shared) >= 2:
        score += min(20, 6 * len(shared))
        why.append("bio shares wording: " + ", ".join(sorted(shared)[:4]))

    loc = profile.get("location", "").strip().lower()
    if loc and any(loc == known.lower() for known in ident["locations"]):
        score += 10
        why.append(f"same declared location ({profile['location']})")

    link = profile.get("link", "").strip().lower()
    if link and any(link == known.lower() for known in ident["links"]):
        score += 15
        why.append("links to the same external URL")

    return min(score, 100), why


def _verdict(score: int) -> str:
    """Deliberately "link", not "identity".

    The strongest thing this evidence can establish is that two accounts are
    connected — the same photo and the same name is equally consistent with one
    person and with someone impersonating them, and the console must not decide
    that for the officer. The reasons list is what they act on.
    """
    if score >= 70:
        return "strong_link"
    if score >= 45:
        return "possible_link"
    return "weak"


# ── handle variants + platform user search ────────────────────────────────

def _variants(u: str) -> list[str]:
    """Handles a person plausibly also owns. Capped — every one costs requests."""
    base = u.lower()
    stem = re.sub(r"[_.\-]?\d+$", "", base) or base
    # Insertion-ordered and de-duplicated, not a set: the same handle must
    # produce the same candidate list every time, or two officers running the
    # same lookup get different answers and neither can reproduce the other's.
    roots = list(dict.fromkeys([
        stem, stem.replace("_", ""), stem.replace(".", ""),
        stem.replace("_", "."), stem.replace(".", "_"),
    ]))
    out: list[str] = []
    for root in roots:
        if len(root) < 3:
            continue
        for cand in (root, f"{root}1", f"{root}_official"):
            if cand != base and _VALID.match(cand) and cand not in out:
                out.append(cand)
    # Six, not sixty: every variant costs a GitHub call, and an anonymous caller
    # only gets 60 an hour to spend across the whole console.
    return out[:6]


async def _search_github(client: httpx.AsyncClient, u: str) -> list[str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": _UA}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    try:
        r = await client.get("https://api.github.com/search/users",
                             params={"q": f"{_core(u)} in:login", "per_page": 5},
                             headers=headers)
        if r.status_code != 200:
            return []
        return [i["login"] for i in (r.json() or {}).get("items", []) if i.get("login")]
    except Exception as exc:                      # noqa: BLE001
        log.debug("github user search failed: %s", exc)
        return []


async def _search_reddit(client: httpx.AsyncClient, u: str, token: str = "") -> list[str]:
    url = ("https://oauth.reddit.com/users/search" if token
           else "https://www.reddit.com/users/search.json")
    headers = {"User-Agent": settings.REDDIT_USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = await client.get(url, params={"q": _core(u), "limit": 5}, headers=headers)
        if r.status_code != 200:
            return []
        children = ((r.json() or {}).get("data") or {}).get("children") or []
        return [c.get("data", {}).get("name") for c in children if c.get("data", {}).get("name")]
    except Exception as exc:                      # noqa: BLE001
        log.debug("reddit user search failed: %s", exc)
        return []


# ── orchestration ─────────────────────────────────────────────────────────

async def _resolve_all(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                       u: str, token: str) -> list[dict]:
    """Every platform, concurrently, for one handle."""

    async def guarded(coro_factory: Callable[[], Awaitable[dict]]) -> dict:
        async with sem:
            return await coro_factory()

    jobs: list[Awaitable[dict]] = [
        guarded(lambda: _github(client, u)),
        guarded(lambda: _reddit(client, u, token)),
        guarded(lambda: _x(client, u)),
        guarded(lambda: _youtube(client, u)),
        guarded(lambda: _instagram(client, u)),
        guarded(lambda: _telegram(client, u)),
    ]
    jobs += [guarded(lambda s=site: _probe(client, s, u)) for site in _PROBE_SITES]
    return list(await asyncio.gather(*jobs))


async def _hash_avatars(client: httpx.AsyncClient, results: list[dict],
                        limit: int = 10) -> None:
    """Attach avatar_hash in place, for the found profiles that have a photo."""
    targets = [r for r in results if r["status"] == "found" and r["avatar"]
               and not _DEFAULT_AVATAR.search(r["avatar"])][:limit]
    hashes = await asyncio.gather(*[_avatar_hash(client, r["avatar"]) for r in targets])
    for r, h in zip(targets, hashes):
        r["avatar_hash"] = h


async def _related(client: httpx.AsyncClient, sem: asyncio.Semaphore, u: str,
                   ident: dict, token: str, budget: int = 12) -> list[dict]:
    """Accounts under a *different* handle that the evidence ties to this person."""
    candidates: list[tuple[str, str]] = [(v, "variant") for v in _variants(u)]
    searched = await asyncio.gather(_search_github(client, u),
                                    _search_reddit(client, u, token))
    seen = {u.lower()} | {c.lower() for c, _ in candidates}
    for names in searched:
        for name in names:
            if name and name.lower() not in seen and _VALID.match(name):
                candidates.append((name, "search"))
                seen.add(name.lower())

    candidates = candidates[:budget]
    if not candidates:
        return []

    async def one(handle: str, origin: str) -> list[dict]:
        async with sem:
            # Cheap, high-signal subset — the full sweep per variant would be
            # dozens of requests against platforms that rate-limit hard.
            profiles = await asyncio.gather(_github(client, handle),
                                            _reddit(client, handle, token),
                                            _x(client, handle))
        hits = [p for p in profiles if p["status"] == "found"]
        for p in hits:
            p["origin"] = origin
        return hits

    found: list[dict] = []
    for group in await asyncio.gather(*[one(h, o) for h, o in candidates]):
        found.extend(group)

    if not found:
        return []

    await _hash_avatars(client, found, limit=12)

    related: list[dict] = []
    for p in found:
        relation = "variant" if p["origin"] == "variant" else "different"
        score, why = _score_against(p, ident, handle_relation=relation, original=u)
        # Below "possible" nothing is shown at all: a coincidence of spelling is
        # not a lead, and a list padded with them buries the one that matters.
        if score < 45:
            continue
        related.append({
            "site": p["site"], "handle": p["handle"] or "", "url": p["url"],
            "display_name": p["display_name"], "bio": p["bio"][:200],
            "avatar": p["avatar"], "followers": p["followers"],
            "confidence": score, "verdict": _verdict(score), "why": why,
            "discovered_by": p["origin"],
        })
    related.sort(key=lambda r: -r["confidence"])
    return related[:12]


async def lookup_username(username: str, *, timeout: float = 8.0,
                          concurrency: int = 8, similar: bool = True) -> dict:
    u = validate(username)
    if not u:
        return {"username": username, "valid": False,
                "error": "Invalid handle (use 2-40 letters, digits, . _ -).",
                "results": [], "summary": {}, "identity": {}, "related": []}

    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits,
                                 follow_redirects=True) as client:
        token = await _reddit_token(client)
        results = await _resolve_all(client, sem, u, token)
        await _hash_avatars(client, results)
        found = [r for r in results if r["status"] == "found"]
        ident = _identity(found, u)

        # Leave-one-out: each profile is corroborated by the *others*, never by
        # itself. With a single profile there is nothing to corroborate it with,
        # so no confidence is claimed at all.
        for r in found:
            peers = [q for q in found if q is not r]
            if not peers:
                continue
            # No handle bonus here: every profile in this sweep was fetched *by*
            # that handle, so "the handle matches" is a restatement of the query,
            # not evidence. What counts is whether anything else lines up.
            score, why = _score_against(r, _identity(peers, u),
                                        handle_relation="none", original=u)
            if why:
                r["match"] = {"confidence": score, "why": why}

        related = await _related(client, sem, u, ident, token) if similar else []

    order = {"found": 0, "blocked": 1, "unknown": 2, "not_found": 3}
    results.sort(key=lambda r: (order.get(r["status"], 9),
                                -(r["followers"] or 0), r["site"]))
    summary = {
        "found": sum(r["status"] == "found" for r in results),
        "not_found": sum(r["status"] == "not_found" for r in results),
        "blocked": sum(r["status"] == "blocked" for r in results),
        "unknown": sum(r["status"] == "unknown" for r in results),
        "checked": len(results),
        "via_api": sum(r["source"] == "api" and r["status"] == "found" for r in results),
    }
    # Which platforms could actually be read, so the UI can say "no token" out
    # loud instead of showing an empty result that looks like an absence.
    coverage = {
        "github": "token" if settings.GITHUB_TOKEN else "anonymous",
        "x": "token" if settings.X_BEARER_TOKEN else "missing",
        "youtube": "key" if settings.YOUTUBE_API_KEY else "missing",
        "reddit": "oauth" if token else "public",
        "instagram": "public",
    }
    return {
        "username": u, "valid": True, "results": results, "summary": summary,
        "related": related,
        "identity": {
            "display_name": ident["display_name"],
            "display_names": ident["display_names"],
            "locations": ident["locations"],
            "links": ident["links"],
            "verified_on": ident["verified_on"],
            "total_reach": ident["total_reach"],
            "avatar": next((r["avatar"] for r in results
                            if r["status"] == "found" and r["avatar"]), ""),
            "bio": next((r["bio"] for r in results
                         if r["status"] == "found" and r["bio"]), ""),
        },
        "coverage": coverage,
    }
