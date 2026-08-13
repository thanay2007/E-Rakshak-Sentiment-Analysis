# -*- coding: utf-8 -*-
"""Emerging-but-unverified detection.

The scenario the mentor described: a post is spreading hard (big reach, fast
engagement, or an alarming claim) but ONLY ONE channel has posted it so far —
no independent source has corroborated it, so we cannot yet call it fake or
real. Those are the posts police most need flagged *early*: if it's a
fabricated rumour, this is the window to act before it goes viral.

A post is flagged EMERGING-UNVERIFIED when all five hold:
  1. Not an established channel — the author is unverified and below
     ESTABLISHED_FOLLOWERS. A national outlet is what corroborates a claim, so
     it cannot also be the uncorroborated claim.
  2. Alarming — concern score at or above CONCERN_FLOOR.
  3. Actually travelling — real interaction volume, and/or engagement
     outrunning the author's own audience. Not "the author is famous".
  4. Single-source — no other distinct account in the window has posted a
     near-identical claim (word-3-gram Jaccard ≥ 0.5). "Only one channel."
  5. Not corroborated — the cross-source fact-check found no independent news
     coverage (or was never able to corroborate it).

Every one of those is a filter *against* the queue, and that is the point: this
list is only useful if being on it means something. An earlier version scored
spread as `0.02 × followers` and waived the spread test entirely for anything
negative, so a wire agency's routine bulletin outranked a post being frantically
reshared, and the queue grew to 260 items — mostly national newspapers and the
police's own account, filed as unverified rumours.

Each flagged item ships with a plain-English reason and a `spread_score` so the
list ranks by urgency, and the counts of what was filtered out are returned
alongside so a short queue is legible rather than suspicious. Computed live (not
stored) so it always reflects the current window.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.database import session_scope
from app.models import Post
from app.services.network_service import _jaccard, _shingles

SPREAD_MIN = 35          # traction threshold (0-100)
SIM_THRESHOLD = 0.5      # near-duplicate similarity
MAX_SCAN = 1500

#: A post has to be *alarming* to be worth a triage slot. Measured against the
#: live corpus this sits above the 90th percentile of concern (median 4, p90
#: 34), so this admits the genuinely hostile tail rather than the day's news.
CONCERN_FLOOR = 25

#: Interactions needed before an engagement *rate* means anything. Eleven likes
#: on a seventy-follower account is a 15% rate, which is not virality — it is a
#: small denominator. Without this floor those posts outrank real spread.
MIN_INTERACTIONS_FOR_RATE = 50

#: An engagement rate this far above the author's own audience reads as the
#: post outrunning the account that made it.
EXCEPTIONAL_RATE = 0.05

#: Verified, or this many followers: an established channel. Such an account is
#: what *corroborates* a claim — it is not the "one obscure channel nobody has
#: confirmed" this queue exists to catch. Their posts are still scored, alerted
#: and searchable everywhere else in the console; they are only kept out of the
#: rumour queue, and the count of them is reported so the omission is visible.
ESTABLISHED_FOLLOWERS = 100_000
# A phrase carried by more than this share of the window is boilerplate and
# would make every post "corroborate" every other one.
_COMMON_SHINGLE_RATIO = 0.10


def _interactions(p: Post) -> float:
    """Weighted engagement. Shares count triple: sharing *is* the spreading."""
    eng = p.engagement or {}
    return ((eng.get("likes", 0) or 0)
            + 3 * (eng.get("shares", 0) or 0)
            + 2 * (eng.get("comments", 0) or 0)
            + (eng.get("views", 0) or 0) / 50)


def _is_established(p: Post) -> bool:
    return bool(p.author_verified) or (p.author_followers or 0) >= ESTABLISHED_FOLLOWERS


def _spread_score(p: Post) -> tuple[float, float, float]:
    """0-100 measure of a post actually travelling, plus its two components.

    The previous version was `0.02 × followers` plus a verified bonus, which
    measured *how famous the author is* rather than whether anything was
    happening. A national outlet's routine bulletin scored 63/100 on follower
    count alone with zero engagement, while a post being frantically reshared
    by a small account scored nothing. That is backwards for a rumour queue,
    and it is why the queue filled with news agencies and the police's own
    posts.

    Now it is traction: how much interaction the post actually drew, and
    whether that interaction outruns the audience the author already had.
    Absolute volume is log-scaled on the same 10^4 curve the concern score
    uses, so the two are read on comparable terms.
    """
    raw = _interactions(p)
    traction = min(1.0, math.log10(1 + raw) / 4)
    if raw >= MIN_INTERACTIONS_FOR_RATE:
        rate = raw / max(p.author_followers or 0, 100)
        outrunning = min(1.0, rate / EXCEPTIONAL_RATE)
    else:
        outrunning = 0.0
    score = 100 * (0.45 * traction + 0.30 * outrunning
                   + 0.25 * (p.concern_score or 0) / 100)
    return round(score, 1), traction, outrunning


def _corroborator_index(posts: list) -> dict[str, set[str]]:
    """For each post id, the set of *other* authors making a near-identical claim.

    Built from an inverted phrase index rather than by comparing every post to
    every other one. The pairwise version is O(n²) — on this window that is over
    a million Jaccard computations per request, which is why the scan had to be
    kept small, and a scan kept small is exactly what makes a "no one else has
    posted this" conclusion unreliable: the corroborating post is simply outside
    the sample.
    """
    shingles = {p.id: _shingles(p.text) for p in posts}
    index: dict[str, list[str]] = defaultdict(list)
    for p in posts:
        for g in shingles[p.id]:
            index[g].append(p.id)

    by_id = {p.id: p for p in posts}
    ceiling = max(2, int(len(posts) * _COMMON_SHINGLE_RATIO))
    neighbours: dict[str, set[str]] = defaultdict(set)
    checked: set[tuple[str, str]] = set()
    for holders in index.values():
        if len(holders) < 2 or len(holders) > ceiling:
            continue
        for pos, a in enumerate(holders):
            for b in holders[pos + 1:]:
                if by_id[a].author_handle == by_id[b].author_handle:
                    continue
                pair = (a, b)
                if pair in checked:
                    continue
                checked.add(pair)
                if _jaccard(shingles[a], shingles[b]) >= SIM_THRESHOLD:
                    neighbours[a].add(by_id[b].author_handle)
                    neighbours[b].add(by_id[a].author_handle)
    return neighbours


#: Computed windows, keyed by hours: (computed_at, payload). The scan costs a
#: multi-second read of every post's engagement and fact-check JSON, while the
#: dashboard panel polls every 45s and the review page pages through the same
#: result — recomputing it per request made paging to page 2 cost as much as
#: the first load. A stale-by-up-to-90s rumour list is the right trade: the
#: ingestion tick is slower than that anyway.
_CACHE: dict[int, tuple[float, dict]] = {}
_CACHE_TTL = 300.0
#: Windows the ingestion tick keeps warm — the two the UI actually opens with.
_PRIMED_WINDOWS = (24, 72)


def prime_cache() -> None:
    """Recompute the common windows ahead of anyone asking for them.

    Called from the ingestion tick (off the event loop). Errors are the
    caller's to swallow: a cold cache is slow, not broken.
    """
    for hours in _PRIMED_WINDOWS:
        _CACHE[hours] = (time.monotonic(), _compute(hours))


def _compute(hours: int) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    with session_scope() as s:
        posts = s.exec(
            # The dozen columns this actually reads, not all thirty-eight.
            # Fifteen hundred posts × the unread remainder — class probability
            # vectors, evidence reports, LLM verification blobs — is a lot of
            # payload to drag across the network to compute a spread score.
            select(Post.id, Post.platform, Post.author_handle, Post.author_name,
                   Post.author_followers, Post.author_verified, Post.text,
                   Post.translation, Post.sentiment_label, Post.concern_score,
                   Post.engagement, Post.fact_check, Post.url, Post.location,
                   Post.language, Post.created_at)
            .where(Post.created_at >= since)
            # Recency, not concern: corroboration has to be judged against the
            # window as it happened. Ordering by concern makes the scan a biased
            # sample of alarming posts, in which quiet corroborating coverage is
            # missing by construction.
            .order_by(Post.created_at.desc()).limit(MAX_SCAN)
        ).all()
    if not posts:
        return {"items": [], "scanned": 0, "platforms": [], "locations": [],
                "dropped": {}}

    corroborators = _corroborator_index(posts)
    dropped = {"established": 0, "low_concern": 0, "not_spreading": 0,
               "corroborated": 0}

    items = []
    for p in posts:
        # An established channel reporting something is the corroboration this
        # queue is looking for the absence of, so it cannot also be the rumour.
        if _is_established(p):
            dropped["established"] += 1
            continue
        # Every post must be alarming *and* travelling. The old code waived the
        # spread test for anything negative, which — since most news is
        # negative — turned the queue into a list of every negative post.
        if (p.concern_score or 0) < CONCERN_FLOOR:
            dropped["low_concern"] += 1
            continue

        spread, traction, outrunning = _spread_score(p)
        if spread < SPREAD_MIN:
            dropped["not_spreading"] += 1
            continue

        fc = p.fact_check or {}
        news_ok = fc.get("verdict") == "corroborated"
        source_count = 1 + len(corroborators.get(p.id, ()))

        # emerging-unverified = spreads, single-source, no independent confirmation
        if source_count > 1 or news_ok:
            dropped["corroborated"] += 1
            continue

        raw = _interactions(p)
        reasons = [f"{int(raw):,} weighted interactions on an account with "
                   f"{p.author_followers:,} followers"]
        if outrunning >= 0.6:
            reasons.append("engagement is outrunning the account's own audience")
        reasons.append(f"concern {round(p.concern_score)}/100 "
                       f"({p.sentiment_label} sentiment)")
        if fc.get("verdict") in ("uncorroborated", "partially corroborated"):
            reasons.append(f"cross-source check: {fc['verdict']} — no independent news coverage")
        else:
            reasons.append("only this account has posted this claim so far — no corroboration")

        items.append({
            "post_id": p.id,
            "platform": p.platform,
            "author_handle": p.author_handle,
            "author_name": p.author_name,
            "author_followers": p.author_followers,
            "author_verified": p.author_verified,
            "text": (p.translation or p.text)[:220],
            "sentiment_label": p.sentiment_label,
            "concern_score": p.concern_score,
            "spread_score": spread,
            "source_count": source_count,
            "url": p.url,
            "location": p.location or "",
            "language": p.language or "",
            "fact_check_verdict": fc.get("verdict", ""),
            "reasons": reasons,
            "created_at": (p.created_at.isoformat() + "Z") if p.created_at else "",
        })

    items.sort(key=lambda x: -x["spread_score"])
    return {
        "items": items,
        "scanned": len(posts),
        "dropped": dropped,
        # Facet values come from the unfiltered result so the filter dropdowns
        # do not shrink to whatever is already selected.
        "platforms": sorted({i["platform"] for i in items if i["platform"]}),
        "locations": sorted({i["location"] for i in items if i["location"]}),
    }


def detect_emerging(hours: int = 24, *, limit: int = 40, offset: int = 0,
                    platform: str = "", location: str = "",
                    min_spread: float = 0.0, sentiment: str = "") -> dict:
    """Filter and page the window's flagged posts (see `_compute` for the scan)."""
    hit = _CACHE.get(hours)
    if hit and (time.monotonic() - hit[0]) < _CACHE_TTL:
        base = hit[1]
    else:
        base = _compute(hours)
        _CACHE[hours] = (time.monotonic(), base)

    items = base["items"]
    if platform:
        items = [i for i in items if i["platform"].lower() == platform.lower()]
    if location:
        items = [i for i in items if i["location"].lower() == location.lower()]
    if sentiment:
        items = [i for i in items if i["sentiment_label"] == sentiment]
    if min_spread:
        items = [i for i in items if i["spread_score"] >= min_spread]

    total = len(items)
    page = items[max(0, offset): max(0, offset) + max(1, limit)]
    return {
        "window_hours": hours,
        "count": len(page),
        "total": total,
        "items": page,
        "scanned": base["scanned"],
        "dropped": base.get("dropped", {}),
        "platforms": base["platforms"],
        "locations": base["locations"],
    }
