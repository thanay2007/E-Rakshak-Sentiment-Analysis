# -*- coding: utf-8 -*-
"""Cross-platform username enumeration (Sherlock / social-analyzer style).

Given a handle, probe a catalogue of public profile URLs and report whether an
account with that name exists on each site. Detection is per-site:
  • "status"  — HTTP 200 means present, 404 means absent
  • "text"    — 200 but the body contains a known 'not found' marker → absent

Everything runs concurrently with a short timeout and a small politeness cap.
Offline / rate-limited probes resolve to "unknown" (never a hard failure) and
the profile URL is always returned so an analyst can open it manually.

This makes only public, unauthenticated GET requests — the same thing typing
the profile URL into a browser does — and never logs in or scrapes content.
"""
from __future__ import annotations

import asyncio
import re

import httpx

# (site, url_template, category, method, marker)
_SITES: list[tuple[str, str, str, str, str]] = [
    ("X / Twitter", "https://twitter.com/{u}", "social", "status", ""),
    ("Instagram", "https://www.instagram.com/{u}/", "social", "status", ""),
    ("Facebook", "https://www.facebook.com/{u}", "social", "status", ""),
    ("YouTube", "https://www.youtube.com/@{u}", "social", "text", "This page isn't available"),
    ("Reddit", "https://www.reddit.com/user/{u}", "social", "text", "nobody on Reddit goes by"),
    ("TikTok", "https://www.tiktok.com/@{u}", "social", "status", ""),
    ("Telegram", "https://t.me/{u}", "messaging", "text", "tgme_page_title"),
    ("Threads", "https://www.threads.net/@{u}", "social", "status", ""),
    ("GitHub", "https://github.com/{u}", "dev", "status", ""),
    ("Pinterest", "https://www.pinterest.com/{u}/", "social", "status", ""),
    ("Medium", "https://medium.com/@{u}", "blog", "status", ""),
    ("Linktree", "https://linktr.ee/{u}", "link-hub", "status", ""),
    ("Snapchat", "https://www.snapchat.com/add/{u}", "social", "status", ""),
    ("Twitch", "https://www.twitch.tv/{u}", "streaming", "status", ""),
    ("VK", "https://vk.com/{u}", "social", "status", ""),
    ("Koo", "https://www.kooapp.com/profile/{u}", "social", "status", ""),
    ("Dailymotion", "https://www.dailymotion.com/{u}", "video", "status", ""),
    ("SoundCloud", "https://soundcloud.com/{u}", "audio", "status", ""),
]

_VALID = re.compile(r"^[A-Za-z0-9._-]{2,40}$")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def validate(username: str) -> str | None:
    u = (username or "").strip().lstrip("@")
    return u if _VALID.match(u) else None


async def _probe(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                 site: tuple, username: str) -> dict:
    name, tmpl, category, method, marker = site
    url = tmpl.format(u=username)
    result = {"site": name, "category": category, "url": url,
              "status": "unknown", "http": None}
    async with sem:
        try:
            r = await client.get(url, follow_redirects=True,
                                  headers={"User-Agent": _UA})
            result["http"] = r.status_code
            if r.status_code == 404:
                result["status"] = "not_found"
            elif r.status_code in (200, 301, 302):
                if method == "text" and marker and marker.lower() in r.text.lower():
                    result["status"] = "not_found"
                else:
                    result["status"] = "found"
            elif r.status_code in (403, 429):
                result["status"] = "blocked"    # site refused the probe
            else:
                result["status"] = "unknown"
        except Exception:
            result["status"] = "unknown"
    return result


async def lookup_username(username: str, *, timeout: float = 5.0,
                          concurrency: int = 8) -> dict:
    u = validate(username)
    if not u:
        return {"username": username, "valid": False,
                "error": "Invalid handle (use 2-40 letters, digits, . _ -).",
                "results": [], "summary": {}}

    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        results = await asyncio.gather(*[_probe(client, sem, s, u) for s in _SITES])

    order = {"found": 0, "blocked": 1, "unknown": 2, "not_found": 3}
    results.sort(key=lambda r: (order.get(r["status"], 9), r["site"]))
    summary = {
        "found": sum(r["status"] == "found" for r in results),
        "not_found": sum(r["status"] == "not_found" for r in results),
        "blocked": sum(r["status"] == "blocked" for r in results),
        "unknown": sum(r["status"] == "unknown" for r in results),
        "checked": len(results),
    }
    return {"username": u, "valid": True, "results": results, "summary": summary}
