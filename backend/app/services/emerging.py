# -*- coding: utf-8 -*-
"""Emerging-but-unverified detection.

The scenario the mentor described: a post is spreading hard (big reach, fast
engagement, or an alarming claim) but ONLY ONE channel has posted it so far —
no independent source has corroborated it, so we cannot yet call it fake or
real. Those are the posts police most need flagged *early*: if it's a
fabricated rumour, this is the window to act before it goes viral.

A post is flagged EMERGING-UNVERIFIED when all three hold:
  1. High projected spread — big author reach, strong engagement, or a high
     threat score (fear/rumour content spreads fastest).
  2. Single-source — no other distinct account in the window has posted a
     near-identical claim (word-3-gram Jaccard ≥ 0.5). "Only one channel."
  3. Not corroborated — the cross-source fact-check found no independent news
     coverage (or was never able to corroborate it).

Each flagged item ships with a plain-English reason and a `spread_score` so the
list ranks by urgency. Computed live (not stored) so it always reflects the
current window.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.database import session_scope
from app.models import Post
from app.services.network_service import _jaccard, _shingles

SPREAD_MIN = 45          # projected-spread threshold (0-100)
SIM_THRESHOLD = 0.5      # near-duplicate similarity
MAX_SCAN = 600


def _reach(p: Post) -> float:
    eng = p.engagement or {}
    interactions = (eng.get("likes", 0) or 0) + 2 * (eng.get("shares", 0) or 0) \
        + (eng.get("comments", 0) or 0) + 0.001 * (eng.get("views", 0) or 0)
    return interactions + 0.02 * (p.author_followers or 0)


def _spread_score(p: Post, reach: float, reach_max: float) -> float:
    """0-100 blend of audience reach, engagement and threat intensity."""
    reach_norm = 100 * (reach / reach_max) if reach_max > 0 else 0
    verified_boost = 15 if p.author_verified else 0   # a blue-check claim travels further
    return round(min(100.0, 0.45 * reach_norm + 0.40 * p.threat_score + verified_boost), 1)


def detect_emerging(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    with session_scope() as s:
        posts = s.exec(
            # The dozen columns this actually reads, not all thirty-eight.
            # Six hundred posts × the unread remainder — class probability
            # vectors, evidence reports, LLM verification blobs — is a lot of
            # payload to drag across the network to compute a spread score.
            select(Post.id, Post.platform, Post.author_handle, Post.author_name,
                   Post.author_followers, Post.author_verified, Post.text,
                   Post.translation, Post.threat_label, Post.threat_score,
                   Post.engagement, Post.fact_check, Post.url, Post.created_at)
            .where(Post.created_at >= since)
            .order_by(Post.threat_score.desc()).limit(MAX_SCAN)
        ).all()
    if not posts:
        return {"window_hours": hours, "count": 0, "items": []}

    reach = {p.id: _reach(p) for p in posts}
    reach_max = max(reach.values()) or 1.0
    shingles = {p.id: _shingles(p.text) for p in posts}

    items = []
    for p in posts:
        spread = _spread_score(p, reach[p.id], reach_max)
        # gate on spread OR an inherently high-risk label
        if spread < SPREAD_MIN and p.threat_label not in ("Fake News", "Incitement to Violence"):
            continue

        # count independent sources: distinct OTHER authors with a similar claim
        corroborators = set()
        for q in posts:
            if q.id == p.id or q.author_handle == p.author_handle:
                continue
            if _jaccard(shingles[p.id], shingles[q.id]) >= SIM_THRESHOLD:
                corroborators.add(q.author_handle)

        fc = p.fact_check or {}
        news_ok = fc.get("verdict") == "corroborated"
        source_count = 1 + len(corroborators)

        # emerging-unverified = spreads, single-source, no independent confirmation
        if source_count > 1 or news_ok:
            continue

        reasons = [f"projected spread {spread}/100 "
                   f"({p.author_followers:,} followers"
                   + (", verified account" if p.author_verified else "") + ")"]
        if p.threat_label != "Neutral":
            reasons.append(f"classified {p.threat_label}")
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
            "threat_label": p.threat_label,
            "threat_score": p.threat_score,
            "spread_score": spread,
            "source_count": source_count,
            "url": p.url,
            "reasons": reasons,
            "created_at": (p.created_at.isoformat() + "Z") if p.created_at else "",
        })

    items.sort(key=lambda x: -x["spread_score"])
    return {"window_hours": hours, "count": len(items), "items": items[:40]}
