# -*- coding: utf-8 -*-
"""Social sleuth — one-shot account dossier.

Given a handle, assemble everything SENTINEL knows about it into a single profile:
  • identity & audience (from the monitored corpus)
  • activity pattern (post volume, cadence, platforms, languages)
  • threat & sentiment footprint (what they post and how hostile it is)
  • authenticity / bot score with the driving signals
  • coordination — whether they appear inside a detected amplification cluster
  • cross-platform presence (live username enumeration)

This is the "social self / sleuth tool": it fuses the corpus footprint with the
username-lookup and bot-scoring modules into a single investigator view.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import mean

from sqlmodel import select

from app.database import session_scope
from app.models import Post
from app.osint.bot_score import score_account
from app.osint.username_lookup import lookup_username


def _find_posts(handle: str) -> list[Post]:
    h = handle.strip().lstrip("@").lower()
    with session_scope() as s:
        # exact first, then prefix / contains for convenience
        rows = s.exec(select(Post).where(Post.author_handle == h)).all()
        if not rows:
            rows = s.exec(select(Post)).all()
            rows = [p for p in rows if h in p.author_handle.lower()]
        return list(rows)


async def build_dossier(handle: str, *, do_username_lookup: bool = True) -> dict:
    h = (handle or "").strip().lstrip("@")
    if not h:
        return {"handle": handle, "found": False, "error": "Empty handle."}

    posts = _find_posts(h)
    dossier: dict = {"handle": h}

    if posts:
        posts.sort(key=lambda p: p.created_at)
        p0 = max(posts, key=lambda p: p.created_at)
        times = [p.created_at for p in posts]
        span_days = max((max(times) - min(times)).total_seconds() / 86400, 0.01)
        posts_per_day = round(len(posts) / span_days, 1) if len(posts) > 1 else len(posts)

        texts = [p.text for p in posts]
        dup = 0.0
        if len(texts) > 1:
            from app.osint.bot_score import near_duplicate_ratio
            dup = max(near_duplicate_ratio(t, texts[:i] + texts[i + 1:])
                      for i, t in enumerate(texts))

        bot = score_account(
            p0.author_handle, name=p0.author_name, followers=p0.author_followers,
            account_age_days=p0.author_account_age_days, verified=p0.author_verified,
            posts_per_day=posts_per_day if len(posts) > 3 else None,
            duplicate_ratio=dup,
        )
        threat_labels = Counter(p.threat_label for p in posts)
        sent = Counter(p.sentiment_label for p in posts)
        worst = sorted(posts, key=lambda p: p.threat_score, reverse=True)[:5]
        clusters = sorted({p.cluster_id for p in posts if p.cluster_id})

        dossier.update({
            "found": True,
            "profile": {
                "author_name": p0.author_name,
                "followers": p0.author_followers,
                "verified": p0.author_verified,
                "account_age_days": p0.author_account_age_days,
                "primary_platform": Counter(p.platform for p in posts).most_common(1)[0][0],
                "platforms": sorted({p.platform for p in posts}),
                "languages": sorted({p.language for p in posts}),
                "locations": sorted({p.location for p in posts if p.location}),
            },
            "activity": {
                "posts_tracked": len(posts),
                "posts_per_day": posts_per_day,
                "first_seen": min(times).isoformat() + "Z",
                "last_seen": max(times).isoformat() + "Z",
                "duplicate_ratio": round(dup, 2),
            },
            "threat_profile": {
                "avg_threat_score": round(mean(p.threat_score for p in posts), 1),
                "max_threat_score": round(max(p.threat_score for p in posts), 1),
                "label_breakdown": dict(threat_labels),
                "non_neutral_posts": sum(l != "Neutral" for l in
                                         (p.threat_label for p in posts)),
            },
            "sentiment_lean": dict(sent),
            "authenticity": bot,
            "coordination": {
                "in_cluster": bool(clusters),
                "cluster_ids": clusters,
                "amplified_posts": sum(p.is_amplified for p in posts),
            },
            "notable_posts": [{
                "platform": p.platform, "threat_label": p.threat_label,
                "threat_score": p.threat_score,
                "text": (p.translation or p.text)[:200],
                "url": p.url, "created_at": p.created_at.isoformat() + "Z",
            } for p in worst],
        })
    else:
        # No corpus footprint — still score the handle string and look it up.
        bot = score_account(h)
        dossier.update({
            "found": False,
            "note": "No posts from this handle in the monitored corpus. "
                    "Scoring the handle string only.",
            "authenticity": bot,
        })

    if do_username_lookup:
        dossier["cross_platform"] = await lookup_username(h)

    return dossier
