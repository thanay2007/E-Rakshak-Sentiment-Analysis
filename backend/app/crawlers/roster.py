"""The accounts this deployment has *discovered*, persisted between runs.

The seed lists in config.py answer "which pages does this deployment always
watch" — a couple of dozen civic, police and news handles, chosen by hand and
verified before they were added. That roster is the right shape for official
sources and the wrong shape for public sentiment: a city's opinion of its
police is not held by its police page, and a hand-maintained list of the four
cities' influencers, food pages, college pages, community desks and local
traders would be out of date the week after it was written.

So the collectors also *find* accounts — Facebook by page search (an offline
discovery run, see facebook_discover.py), Instagram by location feeds and user
search inside the collect loop — and everything found lands here. This file is
the memory between those two halves: discovery writes, the collectors read, and
the account rotation walks seeds and discoveries alike.

Why a JSON file rather than the database: this is crawler configuration, not
evidence. It is rebuilt by re-running discovery, it must be readable and
editable by hand (an officer striking an account off the list is a text edit),
and it must not become another table to migrate. It is written atomically —
a replaced file rather than a truncated one — because a discovery run and a
collect cycle can be in flight at the same time, and a half-written roster
would take a platform down until somebody deleted it.

Entries carry more than the handle so a human can audit the list later: what
the page is called, how big it was when found, which query found it, and when.
A roster whose provenance is unrecorded is one nobody can prune with any
confidence.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Iterable

from app.config import BASE_DIR, settings

log = logging.getLogger("sentinel.crawlers")

ROSTER_FILE = BASE_DIR / "discovered_accounts.json"

# One process, several threads: the ingest loop runs adapters in worker threads
# (asyncio.to_thread), and both Instagram legs can write this file in one cycle.
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_all() -> dict[str, list[dict]]:
    if not ROSTER_FILE.exists():
        return {}
    try:
        data = json.loads(ROSTER_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # a corrupt roster must not take a platform offline
        log.warning("roster: %s unreadable (%s) — treating it as empty",
                    ROSTER_FILE.name, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, list)}


def _write_all(data: dict[str, list[dict]]) -> None:
    tmp = ROSTER_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ROSTER_FILE)  # atomic on both Windows and POSIX


def entries(platform: str) -> list[dict]:
    """Every discovered entry for a platform, oldest first."""
    with _lock:
        return list(_load_all().get(platform.lower(), []))


def handles(platform: str) -> list[tuple[str, str]]:
    """(handle, city) pairs, in the shape the seed settings already use."""
    return [(e["handle"], e.get("city", "")) for e in entries(platform)
            if e.get("handle")]


def merged(platform: str, seeds: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Configured seeds first, then discoveries, deduped on the handle.

    Seeds win on the city tag: they were set deliberately, and a discovery that
    guessed a different city for the same handle should not overwrite that.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for handle, city in list(seeds) + handles(platform):
        key = handle.strip().lstrip("@").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((handle.strip().lstrip("@"), city))
    return out


def add(platform: str, found: Iterable[dict]) -> int:
    """Record newly discovered accounts. Returns how many were actually new.

    A handle already present is left exactly as it was rather than refreshed:
    the follower count on an entry is "how big it was when we found it", and
    rewriting it on every sighting would erase the only evidence of growth this
    file holds. Prune and re-discover to refresh.
    """
    platform = platform.lower()
    with _lock:
        data = _load_all()
        current = data.get(platform, [])
        known = {e.get("handle", "").casefold() for e in current}
        added = 0
        for entry in found:
            handle = (entry.get("handle") or "").strip().lstrip("@")
            if not handle or handle.casefold() in known:
                continue
            known.add(handle.casefold())
            current.append({
                "handle": handle,
                "city": entry.get("city", ""),
                "name": entry.get("name", ""),
                "followers": int(entry.get("followers", 0) or 0),
                "category": entry.get("category", ""),
                "source": entry.get("source", ""),
                "found_at": _now(),
            })
            added += 1
        # Oldest-first, so the cap drops the newest arrivals rather than the
        # accounts that have been earning their place for weeks.
        cap = max(0, settings.ROSTER_MAX_ENTRIES)
        if cap and len(current) > cap:
            log.info("roster: %s roster is at the %d-entry cap — %d newest "
                     "discoveries dropped", platform, cap, len(current) - cap)
            current = current[:cap]
        data[platform] = current
        _write_all(data)
    if added:
        log.info("roster: %d new %s account(s) recorded (%d total)",
                 added, platform, len(current))
    return added


def prune(platform: str, bad_handles: Iterable[str], reason: str = "") -> int:
    """Drop discovered accounts that turned out to be unusable.

    Discovery is deliberately cheap and therefore imprecise — a location feed
    reports whoever posted, which includes private accounts, accounts with nine
    followers, and accounts that have since been deleted. The collector learns
    the truth the first time it reads one, and this is how it says so; without
    it the roster only ever grows and the read budget drains into accounts that
    will never return a post.

    Configured seeds are never touched: they are not in this file.
    """
    targets = {h.strip().lstrip("@").casefold() for h in bad_handles if h}
    if not targets:
        return 0
    platform = platform.lower()
    with _lock:
        data = _load_all()
        current = data.get(platform, [])
        kept = [e for e in current
                if e.get("handle", "").casefold() not in targets]
        removed = len(current) - len(kept)
        if removed:
            data[platform] = kept
            _write_all(data)
    if removed:
        log.info("roster: dropped %d %s account(s)%s", removed, platform,
                 f" — {reason}" if reason else "")
    return removed
