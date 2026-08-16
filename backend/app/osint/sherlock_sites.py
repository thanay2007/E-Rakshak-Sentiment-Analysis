# -*- coding: utf-8 -*-
"""Sherlock's ~480-site manifest, swept with this console's own async client.

The valuable half of Sherlock is not its code, it is `data.json`: for every
site it records the profile URL *and how that host says "no such user"*. That
second part is what a naive probe gets wrong — plenty of sites answer 200 for
a handle that does not exist and put the miss in the page body, and a few
answer 404 for a handle that does. Three detection methods cover them:

    status_code   a missing handle really answers 4xx (HEAD is enough)
    message       the page always answers 200; a miss contains a known string
    response_url  a miss redirects elsewhere, so redirects are disallowed

So this module reads the manifest and re-implements those three checks on
httpx, instead of shelling out to the sherlock CLI. Three reasons: the CLI is
thread-per-request `requests`, which does not belong inside an async endpoint;
its output is meant for a terminal, not for correlation; and a sweep on a live
console needs a *deadline*, which the CLI has no concept of — here whatever
has not answered when the budget runs out is reported as timed-out rather than
guessed.

Everything is an unauthenticated public GET/HEAD. Nothing logs in, and one
dead host degrades that site to "unknown" instead of failing the sweep.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Sherlock sends a plain desktop Firefox UA; several hosts serve a different
# (or no) profile page to anything that looks automated.
_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0")

# Read at most this much of a page before deciding. Every errorMsg fingerprint
# in the manifest lives in the <head> or the first screen of markup, and a
# sweep of 480 sites must not pull 480 full pages through a police network.
_MAX_BODY = 300_000

# A WAF challenge page is neither a profile nor a miss. Sherlock keeps these
# fingerprints because without them a Cloudflare interstitial reads as "found"
# on a message-type site and as "not found" on a status_code one.
_WAF_FINGERPRINTS = (
    ".loading-spinner{visibility:hidden}body.no-js .challenge-running{display:none}",
    '<span id="challenge-error-text">',
    "AwsWafIntegration.forceRefreshToken",
    '{return l.onPageView}}),Object.defineProperty(r,"perimeterxIdentifiers",{enumerable:',
)

_OG = {
    "title": re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']{0,200})', re.I),
    "desc": re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{0,400})', re.I),
    "image": re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']{0,500})', re.I),
}


# ── manifest ──────────────────────────────────────────────────────────────

#: The manifest shipped with the console. Only this one file of Sherlock is
#: used — not its CLI, tests or packaging — so a copy lives here rather than
#: the whole 1.4 MB checkout, and the console works on a fresh clone with no
#: extra download. MIT licence beside it as SHERLOCK_LICENSE.
_BUNDLED_MANIFEST = Path(__file__).resolve().parent / "resources" / "sherlock_data.json"


def _manifest_path() -> Path | None:
    """Locate `data.json`: a local checkout first, else the bundled copy.

    A `sherlock-master/` folder next to the repo wins when it is there, so an
    operator can drop in a newer manifest without waiting for a release.
    `sherlock-master/sherlock-master/…` (a GitHub zip extracted into a folder
    of the same name) is as likely as a flat `sherlock-master/…`, so the
    configured directory is searched rather than assumed.
    """
    root = Path(settings.SHERLOCK_DIR)
    direct = root / "sherlock_project" / "resources" / "data.json"
    if direct.is_file():
        return direct
    if root.is_dir():
        # Deterministic: the same folder must resolve to the same manifest on
        # every run, and glob order is filesystem-dependent.
        found = sorted(root.glob("*/sherlock_project/resources/data.json"))
        if found:
            return found[0]
    return _BUNDLED_MANIFEST if _BUNDLED_MANIFEST.is_file() else None


@lru_cache(maxsize=1)
def load_sites() -> dict[str, dict[str, Any]]:
    """The manifest, keyed by site name. Cached — it is ~1 MB of JSON."""
    path = _manifest_path()
    if path is None:
        log.info("sherlock manifest not found under %s — sweep disabled",
                 settings.SHERLOCK_DIR)
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                          # noqa: BLE001
        log.warning("sherlock manifest at %s is unreadable: %s", path, exc)
        return {}
    # "$schema" is metadata, not a site.
    sites = {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("url")}
    log.info("sherlock manifest loaded: %d sites from %s", len(sites), path)
    return sites


# Sherlock keeps a second list beside the manifest: sites whose fingerprint has
# drifted far enough that they report a hit for everyone. Its CLI honours it by
# default (sites.py, honor_exclusions=True), so this does too. A snapshot ships
# with the console because a police server may have no route to GitHub, and the
# live list is refreshed over it at most once a day.
_EXCLUSIONS_URL = ("https://raw.githubusercontent.com/sherlock-project/sherlock/"
                   "refs/heads/exclusions/false_positive_exclusions.txt")
_EXCLUSIONS_FILE = Path(__file__).resolve().parent / "resources" / "sherlock_exclusions.txt"
_EXCLUSIONS_TTL = 24 * 3600.0
_exclusions_cache: tuple[float, set[str]] | None = None


def _parse_exclusions(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if line.strip()}


def _bundled_exclusions() -> set[str]:
    try:
        return _parse_exclusions(_EXCLUSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:                                 # noqa: BLE001
        return set()


async def exclusions() -> set[str]:
    """Site names to skip, refreshed from upstream when the network allows."""
    global _exclusions_cache
    if not settings.SHERLOCK_HONOR_EXCLUSIONS:
        return set()
    now = time.monotonic()
    if _exclusions_cache and now - _exclusions_cache[0] < _EXCLUSIONS_TTL:
        return _exclusions_cache[1]

    names = _bundled_exclusions()
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(_EXCLUSIONS_URL)
        if r.status_code == 200 and r.text.strip():
            fetched = _parse_exclusions(r.text)
            if fetched:
                names = fetched
                try:
                    _EXCLUSIONS_FILE.write_text(r.text, encoding="utf-8")
                except Exception as exc:              # noqa: BLE001 — read-only install is fine
                    log.debug("could not refresh the exclusions snapshot: %s", exc)
    except Exception as exc:                          # noqa: BLE001
        log.debug("exclusions refresh failed, using the bundled list: %s", exc)

    _exclusions_cache = (now, names)
    return names


def available() -> bool:
    return bool(settings.SHERLOCK_ENABLED and load_sites())


def site_count() -> int:
    return len(load_sites())


# ── one site ──────────────────────────────────────────────────────────────

def _interpolate(value: Any, username: str) -> Any:
    """Sherlock's `{}` substitution, over strings, lists and dicts alike."""
    if isinstance(value, str):
        return value.replace("{}", username)
    if isinstance(value, list):
        return [_interpolate(v, username) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate(v, username) for k, v in value.items()}
    return value


def _row(site: str, url: str) -> dict:
    """Same keys as username_lookup's `_blank`, so the two merge without a branch.

    Deliberately not imported from there: that module imports this one, and a
    shared row constructor either way round is an import cycle.
    """
    return {
        "site": site, "category": "web", "url": url,
        "status": "unknown", "http": None, "source": "sherlock",
        "handle": "", "display_name": "", "bio": "", "avatar": "",
        "followers": None, "created_at": "", "verified": False,
        "location": "", "link": "", "extra": {},
    }


async def _fetch(client: httpx.AsyncClient, method: str, url: str, *,
                 headers: dict, allow_redirects: bool, payload: Any,
                 want_body: bool) -> tuple[int, str]:
    """One request, with the body capped rather than swallowed whole."""
    kwargs: dict[str, Any] = {"headers": headers, "follow_redirects": allow_redirects}
    if payload is not None:
        kwargs["json"] = payload
    if not want_body:
        r = await client.request(method, url, **kwargs)
        return r.status_code, ""

    chunks: list[bytes] = []
    size = 0
    async with client.stream(method, url, **kwargs) as r:
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if size >= _MAX_BODY:
                break
        encoding = r.encoding or "utf-8"
        status = r.status_code
    return status, b"".join(chunks).decode(encoding, "replace")


def _error_types(info: dict) -> list[str]:
    et = info.get("errorType")
    return [et] if isinstance(et, str) else list(et or [])


def _claimed(info: dict, status: int, text: str) -> str:
    """Sherlock's verdict logic, in the order the CLI applies it."""
    types = _error_types(info)
    if any(t not in ("message", "status_code", "response_url") for t in types):
        return "unknown"

    verdict = "unknown"

    if "message" in types:
        errors = info.get("errorMsg") or []
        if isinstance(errors, str):
            errors = [errors]
        # The miss fingerprint being absent is what marks the handle as taken.
        verdict = "not_found" if any(e in text for e in errors) else "found"

    if "status_code" in types and verdict != "not_found":
        codes = info.get("errorCode")
        if isinstance(codes, int):
            codes = [codes]
        if codes and status in codes:
            verdict = "not_found"
        elif status >= 300 or status < 200:
            verdict = "not_found"
        else:
            verdict = "found"

    if "response_url" in types and verdict != "not_found":
        # Redirects were disallowed for this method, so a 2xx on the profile
        # URL itself is the hit; anything else redirected away from it.
        verdict = "found" if 200 <= status < 300 else "not_found"

    if verdict == "found" and "status_code" not in types and status >= 400:
        # A message-type site is read by looking for its "no such user" string
        # in the page. An error response has no page to look in — its body is
        # the host's own 404 or its bot wall — so the string is missing for a
        # reason that has nothing to do with the handle. Sherlock calls that a
        # hit; measured against this manifest's own known-good handles, it is
        # where most of its false positives come from.
        verdict = "not_found" if status in (404, 410) else "blocked"

    return verdict


async def _check(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                 name: str, info: dict, username: str) -> dict | None:
    """Check one site. `None` means the handle is not even legal there."""
    regex = info.get("regexCheck")
    if regex:
        try:
            if re.search(regex, username) is None:
                return None
        except re.error:                              # a bad pattern is the manifest's problem
            pass

    url = _interpolate(info["url"], username)
    out = _row(name, url)
    if info.get("isNSFW"):
        out["category"] = "adult"
        out["extra"]["nsfw"] = True

    types = _error_types(info)
    # status_code sites need no body, so HEAD keeps the sweep cheap; the other
    # two methods read the page because the answer is *in* the page.
    method = (info.get("request_method")
              or ("HEAD" if types == ["status_code"] else "GET")).upper()
    if "message" in types and method == "HEAD":
        # No manifest entry does this today, but one could: a message-type site
        # checked with HEAD has no body to search, so the miss string is always
        # "absent" and every handle would read as found.
        method = "GET"
    want_body = method != "HEAD"
    # response_url detects the miss by *being redirected*, so following the
    # redirect would erase the very signal being measured.
    allow_redirects = "response_url" not in types

    headers = {"User-Agent": _UA}
    headers.update(info.get("headers") or {})
    probe = _interpolate(info.get("urlProbe") or info["url"], username)
    payload = _interpolate(info.get("request_payload"), username) \
        if info.get("request_payload") is not None else None

    async with sem:
        try:
            status, text = await _fetch(
                client, method, probe, headers=headers,
                allow_redirects=allow_redirects, payload=payload,
                want_body=want_body)
        except httpx.TimeoutException:
            out["extra"]["note"] = "no answer within the per-site timeout"
            return out
        except Exception as exc:                      # noqa: BLE001 — one dead host is not a failed sweep
            log.debug("sherlock check failed for %s/%s: %s", name, username, exc)
            out["extra"]["note"] = "host unreachable"
            return out

    out["http"] = status
    if text and any(f in text for f in _WAF_FINGERPRINTS):
        out["status"] = "blocked"
        out["extra"]["note"] = "bot-protection page — the site would not answer the probe"
        return out

    verdict = _claimed(info, status, text)
    out["status"] = verdict
    if verdict == "found":
        out["handle"] = username
        # OpenGraph is the only metadata a probe can honestly claim — and it is
        # what lets these hits join the photo/name correlation instead of just
        # being a list of links.
        if text:
            title = _OG["title"].search(text)
            desc = _OG["desc"].search(text)
            image = _OG["image"].search(text)
            if title:
                out["display_name"] = title.group(1).strip()[:120]
            if desc:
                out["bio"] = desc.group(1).strip()[:400]
            if image:
                out["avatar"] = image.group(1).strip()
    return out


# ── sweep ─────────────────────────────────────────────────────────────────

def _control_handles(username: str) -> list[str]:
    """Handles nobody owns, used to test whether a site can tell them apart.

    Derived from the query rather than random: two officers running the same
    lookup have to get the same answer, and a control that changes per run
    makes a discarded hit impossible to reproduce.
    """
    digest = hashlib.sha256(f"sentinel-control:{username.lower()}".encode()).hexdigest()
    # A letter first and hex after it satisfies nearly every regexCheck in the
    # manifest, and 13 characters is long enough that no real account collides.
    return ["z" + digest[:12], "q" + digest[12:24]]


async def _verify_hits(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                       hits: list[dict], targets: dict[str, dict],
                       username: str, budget: float) -> int:
    """Re-run each hit against a handle nobody owns, and drop the ones it matches.

    Roughly one site in fourteen in this manifest has drifted: it answers the
    same page for a real profile and for an invented one, so *every* handle
    "exists" there. Measured on a control handle, that produced 32 hits out of
    455 — noise that a probe-only tool has no way to notice, and that in a case
    file reads exactly like a finding.

    A hit only survives if the same check says "not found" for the control. It
    costs one extra request per hit, which is a tiny fraction of the sweep.

    Rows are marked in place (`status` becomes "unreliable"); the count of
    those is returned so the summary can say how many sites were thrown away.
    """
    controls = _control_handles(username)
    jobs: dict[asyncio.Task, dict] = {}
    for row in hits:
        info = targets.get(row["site"])
        if not info:
            continue
        regex = info.get("regexCheck")
        control = next((c for c in controls if not regex or re.search(regex, c)), "")
        if not control:
            row["extra"]["note"] = "not re-tested — no control handle is legal on this site"
            continue
        jobs[asyncio.create_task(_check(client, sem, row["site"], info, control))] = row

    if not jobs:
        return 0

    done, pending = await asyncio.wait(list(jobs), timeout=budget)
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    discarded = 0
    for t in done:
        row = jobs[t]
        if t.cancelled() or t.exception() is not None:
            continue
        control_row = t.result()
        if control_row is None:
            continue
        if control_row["status"] == "found":
            row["status"] = "unreliable"
            discarded += 1
        elif control_row["status"] == "not_found":
            row["extra"]["verified"] = True

    return discarded


async def sweep(username: str, *, include_nsfw: bool | None = None,
                budget: float | None = None, verify: bool = True) -> dict:
    """Check the whole manifest for one handle, inside a hard deadline.

    Returns the hits (and the sites that blocked the probe) plus counts for
    everything else. The misses are counted, not listed: 450 rows of "no
    account here" is not evidence an officer can use, and it would bury the
    dozen rows that are.
    """
    sites = load_sites() if settings.SHERLOCK_ENABLED else {}
    empty = {"results": [], "checked": 0, "found": 0, "not_found": 0,
             "blocked": 0, "unknown": 0, "skipped": 0, "timed_out": 0,
             "excluded": 0, "manifest": len(sites)}
    if not sites:
        return empty

    nsfw = settings.SHERLOCK_INCLUDE_NSFW if include_nsfw is None else include_nsfw
    excluded = await exclusions()
    targets = {n: i for n, i in sites.items()
               if (nsfw or not i.get("isNSFW")) and n not in excluded}
    if not targets:
        return {**empty, "excluded": len(sites)}

    concurrency = max(4, settings.SHERLOCK_CONCURRENCY)
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency,
                          max_keepalive_connections=concurrency)
    counts = {"found": 0, "not_found": 0, "blocked": 0, "unknown": 0}
    results: list[dict] = []
    skipped = 0
    timed_out = 0
    unreliable = 0
    total_budget = budget if budget is not None else settings.SHERLOCK_BUDGET
    # The control pass only re-checks the hits — a small fraction of the sweep —
    # so it gets a small slice of the deadline, and the main pass keeps the rest.
    verify_budget = max(4.0, total_budget * 0.25)

    async with httpx.AsyncClient(timeout=settings.SHERLOCK_TIMEOUT, limits=limits,
                                 follow_redirects=False, verify=True) as client:
        tasks = [asyncio.create_task(_check(client, sem, name, info, username))
                 for name, info in targets.items()]
        done, pending = await asyncio.wait(tasks, timeout=total_budget)
        timed_out = len(pending)
        for t in pending:
            t.cancel()
        if pending:
            # Await the cancellations *inside* the client context: a cancelled
            # request still holds a connection, and closing the client under it
            # is what turns a slow sweep into a pool of unclosed sockets.
            await asyncio.gather(*pending, return_exceptions=True)

        for t in done:
            if t.cancelled() or t.exception() is not None:
                continue
            row = t.result()
            if row is None:
                skipped += 1                          # handle illegal on that site
                continue
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            # Misses are counted only. Hits and blocks are what an officer acts on.
            if row["status"] in ("found", "blocked"):
                results.append(row)

        if verify:
            hits = [r for r in results if r["status"] == "found"]
            unreliable = await _verify_hits(client, sem, hits, targets,
                                            username, verify_budget)
            results = [r for r in results if r["status"] != "unreliable"]
            counts["found"] -= unreliable
            counts["unreliable"] = unreliable

    results.sort(key=lambda r: (r["status"] != "found", r["site"].lower()))
    return {
        "results": results,
        "checked": len(targets) - skipped,
        "skipped": skipped,
        "timed_out": timed_out,
        "manifest": len(sites),
        "excluded": len(sites) - len(targets),
        **counts,
    }
