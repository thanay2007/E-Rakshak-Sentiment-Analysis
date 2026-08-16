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

import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

from sqlmodel import select

from app.database import session_scope
from app.models import Post
from app.ml.normalize import normalize
from app.osint.bot_score import score_account

log = logging.getLogger("sentinel.osint")


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


# A shingle appearing in more than this share of the window is boilerplate
# ("in the city of", a platform's own footer) and links everything to
# everything if it is allowed to drive candidate generation.
_COMMON_SHINGLE_RATIO = 0.10
MAX_SCAN = 4000


def _cluster(posts: list[Post], min_accounts: int = 3) -> list[list[Post]]:
    """Near-duplicate clusters across the whole window, every sentiment.

    Two things were wrong with comparing only negative posts. A whitewash
    campaign — the same laudatory copy pushed by fifty accounts — is *positive*
    by construction, so the branch that names one could never fire. And the
    comparison was O(n²), which is why it was capped at the first 400 rows the
    database happened to return; on a 10,000-post window that is a sample, not
    a search, and the campaign was as likely to be outside it as in it.

    So: candidates are generated from an inverted shingle index (only posts
    that actually share phrasing are ever compared), which keeps the work
    proportional to real overlap rather than to the square of the window.
    """
    cand = [p for p in posts if p.text and len(p.text.split()) >= 4][:MAX_SCAN]
    if len(cand) < 2:
        return []

    sh = [_shingles(p.text) for p in cand]

    index: dict[str, list[int]] = defaultdict(list)
    for i, shingles in enumerate(sh):
        for g in shingles:
            index[g].append(i)

    ceiling = max(2, int(len(cand) * _COMMON_SHINGLE_RATIO))
    uf = _UF(len(cand))
    compared: set[tuple[int, int]] = set()
    for holders in index.values():
        if len(holders) < 2 or len(holders) > ceiling:
            continue
        for a_pos, i in enumerate(holders):
            for j in holders[a_pos + 1:]:
                pair = (i, j)
                if pair in compared:
                    continue
                compared.add(pair)
                if _jaccard(sh[i], sh[j]) >= 0.5:
                    uf.union(i, j)

    groups: dict[int, list[Post]] = defaultdict(list)
    for i, p in enumerate(cand):
        groups[uf.find(i)].append(p)
    return [g for g in groups.values()
            if len({p.author_handle for p in g}) >= min_accounts]


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
    "image_whitewash": "Coordinated whitewash / paid praise",
    "narrative_push": "Coordinated narrative push",
}


def detect_pr_campaigns(hours: int = 48, min_accounts: int = 3) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    with session_scope() as s:
        # The fifteen columns this reads, not all thirty-eight: four thousand
        # rows × class-probability vectors, evidence dossiers and LLM
        # verification blobs is a great deal of payload to drag out of a
        # database that may be in another region, to compute a shingle overlap.
        posts = s.exec(
            select(Post.id, Post.platform, Post.author_handle,
                   Post.author_followers, Post.author_account_age_days,
                   Post.author_verified, Post.text, Post.translation,
                   Post.sentiment_label, Post.concern_score, Post.engagement,
                   Post.hashtags, Post.location, Post.is_amplified,
                   Post.created_at)
            .where(Post.created_at >= since)
            .order_by(Post.created_at.desc()).limit(MAX_SCAN)
        ).all()

    clusters = _cluster(posts, min_accounts=min_accounts)
    neutral_clusters = 0
    campaigns = []
    for idx, group in enumerate(sorted(clusters, key=len, reverse=True)):
        labels = Counter(p.sentiment_label for p in group)
        # Scope filter: a coordinated cluster of neutral logistics posts is a
        # marketing schedule, not something this console should surface.
        if labels.most_common(1)[0][0] == "neutral":
            neutral_clusters += 1
            continue

        handles = sorted({p.author_handle for p in group})
        platforms = sorted({p.platform for p in group if p.platform})
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
        if len(platforms) > 1:
            # Identical copy appearing on several platforms at once is not how
            # a message spreads organically — someone distributed it.
            conf += 0.10
            why.append(f"same copy posted across {len(platforms)} platforms "
                       f"({', '.join(platforms)})")

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
            "platforms": platforms,
            "locations": sorted({p.location for p in group if p.location}),
            "first_seen": min(times).isoformat() + "Z",
            "last_seen": max(times).isoformat() + "Z",
            "spread_minutes": int(spread // 60),
            "avg_concern": round(mean(p.concern_score for p in group), 1),
            # Enough posts to open the actual evidence from the UI, not the
            # whole cluster — a 200-post campaign should not ship 200 bodies.
            "sample_posts": [
                {"id": p.id, "platform": p.platform, "author_handle": p.author_handle,
                 "text": (p.translation or p.text)[:180],
                 "concern_score": p.concern_score,
                 "created_at": p.created_at.isoformat() + "Z"}
                for p in sorted(group, key=lambda q: -q.concern_score)[:6]
            ],
        })

    campaigns.sort(key=lambda c: (-c["confidence"], -c["reach_estimate"]))
    return {
        "window_hours": hours,
        "campaigns_found": len(campaigns),
        "campaigns": campaigns,
        # Shown in the UI so an empty result reads as "nothing coordinated in
        # this window", not as "the detector did not run".
        "posts_scanned": len(posts),
        "clusters_found": len(clusters),
        "neutral_clusters_ignored": neutral_clusters,
        "min_accounts": min_accounts,
        "note": "A campaign here is ≥3 accounts posting near-identical copy. "
                "Neutral clusters are ignored as ordinary syndication.",
    }


# ── dashboard KPI ───────────────────────────────────────────────────────────
#
# The full detection is a shingle overlap plus a bot score per author over the
# whole window — about five seconds on live data, which is why the endpoint
# that serves it is marked Expensive. The dashboard polls its KPIs every
# fifteen seconds, so the count gets its own small cache and is primed from the
# ingestion tick, exactly as the emerging-rumour window is.

_COUNT_CACHE: tuple[float, int] | None = None
_COUNT_TTL = 600.0
#: The window the dashboard tile reports on. Longer than the rumour queue's on
#: purpose: a coordinated push is assembled over a day or two, and a 24h view
#: cuts campaigns in half.
KPI_WINDOW_HOURS = 48


def campaign_count(*, refresh: bool = False) -> int:
    """How many law-and-order fake-PR campaigns are live in the KPI window.

    Returns the last known count on failure rather than raising: this feeds a
    dashboard tile, and a detector that could not run is not the same thing as
    zero campaigns — but neither is it a reason to fail the whole stats call.
    """
    global _COUNT_CACHE

    if _COUNT_CACHE and not refresh and (time.monotonic() - _COUNT_CACHE[0]) < _COUNT_TTL:
        return _COUNT_CACHE[1]
    try:
        found = detect_pr_campaigns(hours=KPI_WINDOW_HOURS)["campaigns_found"]
    except Exception:
        log.warning("fake-PR campaign count failed", exc_info=True)
        return _COUNT_CACHE[1] if _COUNT_CACHE else 0
    _COUNT_CACHE = (time.monotonic(), found)
    return found


def prime_count_cache() -> None:
    """Recompute the KPI count ahead of anyone asking. Called off the event
    loop from the ingestion tick; a cold cache is slow, not broken."""
    campaign_count(refresh=True)
