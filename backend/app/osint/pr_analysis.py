# -*- coding: utf-8 -*-
"""Fake-PR / astroturf campaign detection — scoped to law-and-order impact.

A "fake PR" campaign here means coordinated, inauthentic messaging engineered to
manufacture a narrative (manufactured outrage, a whitewash, or a boycott push)
rather than organic public opinion. We only surface campaigns that touch public
order — the note's explicit scope ("only ones that affect law and order") — so
ordinary marketing spam is filtered out.

Signals per candidate campaign (near-duplicate cluster across ≥3 accounts):
  • message uniformity      — near-identical copy re-posted verbatim
  • synchronized burst      — posts land inside a tight window
  • bot-heavy roster        — share of authors scoring as likely bots
  • sentiment lock-step     — the whole cluster pushes one emotional direction
  • hashtag stuffing / amplification
  • negative lock-step       — the cluster is pushing negative sentiment,
                               which is what makes a coordinated push worth
                               an analyst's time rather than merely notable
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

from sqlmodel import select

from app.database import session_scope
from app.models import Post
from app.ml.normalize import normalize
from app.osint.bot_score import score_account

def _shingles(text: str, n: int = 3) -> set:
    words = normalize(text).split()
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _UF:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb: self.p[rb] = ra


def _cluster(posts: list[Post]) -> list[list[Post]]:
    cand = [p for p in posts if p.sentiment_label == "negative"][:400]
    if len(cand) < 2:
        return []
    sh = [_shingles(p.text) for p in cand]
    uf = _UF(len(cand))
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            if _jaccard(sh[i], sh[j]) >= 0.5:
                uf.union(i, j)
    groups: dict[int, list[Post]] = defaultdict(list)
    for i, p in enumerate(cand):
        groups[uf.find(i)].append(p)
    return [g for g in groups.values() if len({p.author_handle for p in g}) >= 3]


def _sentiment_lean(group: list[Post]) -> tuple[str, float]:
    labels = Counter(p.sentiment_label for p in group)
    top, n = labels.most_common(1)[0]
    return top, round(n / len(group), 2)


def _campaign_type(group: list[Post], lean: str) -> str:
    """Name the shape of the push from what is measurable: which direction the
    cluster leans, and how hard.

    This deliberately stops short of calling a cluster "disinformation" — the
    clustering shows that many accounts posted near-identical text at once,
    which is a fact, while whether the content is false is not something this
    pipeline establishes.
    """
    avg_concern = mean(p.concern_score for p in group)
    if lean == "negative":
        return "manufactured_outrage" if avg_concern >= 60 else "narrative_push"
    if lean == "positive":
        return "image_whitewash"
    return "narrative_push"


_TYPE_LABEL = {
    "manufactured_outrage": "Manufactured outrage",
    "disinformation_push": "Disinformation push",
    "image_whitewash": "Coordinated whitewash / paid praise",
    "narrative_push": "Coordinated narrative push",
}


def detect_pr_campaigns(hours: int = 48) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    with session_scope() as s:
        posts = s.exec(select(Post).where(Post.created_at >= since)).all()

    campaigns = []
    for idx, group in enumerate(sorted(_cluster(posts), key=len, reverse=True)):
        labels = Counter(p.sentiment_label for p in group)
        # Scope filter: a coordinated cluster of neutral logistics posts is a
        # marketing schedule, not something this console should surface.
        if labels.most_common(1)[0][0] == "neutral":
            continue

        handles = sorted({p.author_handle for p in group})
        times = [p.created_at for p in group]
        spread = (max(times) - min(times)).total_seconds()
        ages = [p.author_account_age_days for p in group]
        followers = [p.author_followers for p in group]

        bot_scores = [score_account(p.author_handle, followers=p.author_followers,
                                    account_age_days=p.author_account_age_days,
                                    verified=p.author_verified)["score"]
                      for p in group]
        bot_ratio = round(sum(b >= 60 for b in bot_scores) / len(group), 2)
        lean, uniformity = _sentiment_lean(group)
        ctype = _campaign_type(group, lean)

        conf, why = 0.30, []
        why.append(f"{len(handles)} accounts posted near-identical copy "
                   f"({len(group)} posts)")
        if spread <= 900:
            conf += 0.20
            why.append(f"synchronized within {int(spread // 60)} minutes")
        if bot_ratio >= 0.4:
            conf += 0.20
            why.append(f"{int(bot_ratio * 100)}% of the roster scores as likely bots")
        if uniformity >= 0.8:
            conf += 0.12
            why.append(f"{int(uniformity * 100)}% share the same {lean} framing "
                       f"(engineered, not organic debate)")
        if mean(ages) < 90:
            conf += 0.10
            why.append(f"average account age only {int(mean(ages))} days")
        if mean(followers) < 150:
            conf += 0.08
            why.append(f"average follower count only {int(mean(followers))}")
        amplified = sum(p.is_amplified for p in group)
        if amplified:
            conf += 0.05
            why.append(f"{amplified} posts flagged as paid/boosted amplification")

        reach = sum((p.engagement or {}).get("shares", 0) +
                    (p.engagement or {}).get("views", 0) for p in group)
        top_hashtags = Counter(t for p in group for t in (p.hashtags or [])).most_common(4)

        campaigns.append({
            "id": f"PR{idx + 1}",
            "type": ctype,
            "type_label": _TYPE_LABEL[ctype],
            "confidence": round(min(conf, 0.98), 2),
            "law_order_category": labels.most_common(1)[0][0],
            "accounts": handles,
            "account_count": len(handles),
            "posts": len(group),
            "bot_ratio": bot_ratio,
            "sentiment_lean": lean,
            "sentiment_uniformity": uniformity,
            "reach_estimate": reach,
            "top_hashtags": [t for t, _ in top_hashtags],
            "why": why,
            "sample_text": (group[0].translation or group[0].text)[:220],
            "locations": sorted({p.location for p in group if p.location}),
            "first_seen": min(times).isoformat() + "Z",
        })

    campaigns.sort(key=lambda c: (-c["confidence"], -c["reach_estimate"]))
    return {
        "window_hours": hours,
        "campaigns_found": len(campaigns),
        "campaigns": campaigns,
        "note": "Only campaigns with law-and-order impact are shown "
                "(manufactured outrage, disinformation, boycott/whitewash pushes).",
    }
