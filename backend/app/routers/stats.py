"""GET /api/stats — every number the dashboard KPIs and overview charts need,
including LIVE classification accuracy against simulated ground truth."""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.config import SENTIMENT_LABELS, settings
from app.crawlers.registry import platform_status
from app.database import get_session
from app.models import Alert, Post
from app.osint.pr_analysis import campaign_count
from app.services.emerging import detect_emerging

log = logging.getLogger("sentinel.stats")
router = APIRouter()


def _hour_buckets(posts, hours: int, key=lambda p: 1) -> list[int]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    buckets = [0] * hours
    for p in posts:
        idx = int((now - p.created_at).total_seconds() // 3600)
        if 0 <= idx < hours:
            buckets[hours - 1 - idx] += key(p)
    return buckets


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since24 = now - timedelta(hours=24)
    total_posts = session.exec(select(func.count()).select_from(Post)).one()
    # Only the columns the numbers below are made of. `select(Post)` fetches
    # all thirty-eight, including the post text, its translation, the class
    # probability vector and any evidence report — none of which this endpoint
    # reads, and all of which cross the network to a database that is not in
    # this country. The rows still support attribute access, so everything
    # downstream is unchanged.
    posts24 = session.exec(
        select(Post.created_at, Post.platform, Post.sentiment_label,
               Post.concern_score, Post.true_label)
        .where(Post.created_at >= since24)
    ).all()
    alerts24 = session.exec(
        select(Alert.created_at, Alert.severity)
        .where(Alert.created_at >= since24)
    ).all()
    open_critical = session.exec(
        select(func.count()).select_from(Alert)
        .where(Alert.severity == "critical", Alert.status == "new")
    ).one()

    # "Flagged" = negative sentiment that is also getting traction. The score
    # already weights negativity, but the tag check keeps the KPI honest:
    # this number is what the label on the dashboard says it is. Still used by
    # the per-platform bar chart, which shows flagged volume per source.
    flagged24 = [p for p in posts24
                 if p.sentiment_label == "negative"
                 and p.concern_score >= settings.ALERT_THRESHOLD]
    platforms = platform_status()

    # The three tiles an officer can act on, each the headline number of a page
    # they can open. A KPI with no page behind it is decoration: "Bot Swarm
    # Campaigns: 3" named a cluster count with nothing to click through to,
    # while the actual coordinated-campaign detector sat unlinked on another
    # screen. Both of these come from caches primed by the ingestion tick — the
    # dashboard polls this endpoint every fifteen seconds and neither scan is
    # anywhere near that cheap to run on demand.
    alert_posts = len(alerts24)
    fake_pr_campaigns = campaign_count()
    try:
        unverified_rumours = detect_emerging(24, limit=1)["total"]
    except Exception:                       # a cold/failed scan is not a stats outage
        log.warning("unverified-rumour count failed", exc_info=True)
        unverified_rumours = 0

    # KPI deltas: last 12h vs previous 12h
    def _delta(items, ts=lambda p: p.created_at):
        half = now - timedelta(hours=12)
        recent = sum(1 for i in items if ts(i) >= half)
        prev = len(items) - recent
        return round((recent - prev) / max(prev, 1) * 100)

    sentiment_series = defaultdict(lambda: {"positive": 0, "neutral": 0, "negative": 0})
    for p in posts24:
        idx = 23 - min(23, int((now - p.created_at).total_seconds() // 3600))
        sentiment_series[idx][p.sentiment_label] += 1
    sentiment_24h = [
        {"hour": (now - timedelta(hours=23 - i)).strftime("%H:00"), **sentiment_series[i]}
        for i in range(24)
    ]

    platform_counts = Counter(p.platform for p in posts24)
    platform_threats = Counter(p.platform for p in flagged24)
    platform_activity = [
        {"platform": pf, "posts": c, "threats": platform_threats.get(pf, 0)}
        for pf, c in platform_counts.most_common()
    ]

    # Live classification accuracy vs simulated ground truth
    labeled = [p for p in posts24 if p.true_label]
    correct = sum(1 for p in labeled if p.sentiment_label == p.true_label)
    per_class = {}
    for lbl in SENTIMENT_LABELS:
        cls = [p for p in labeled if p.true_label == lbl]
        if cls:
            per_class[lbl] = round(sum(1 for p in cls if p.sentiment_label == lbl) / len(cls) * 100, 1)

    return {
        "kpis": {
            "posts_monitored": total_posts,
            "posts_monitored_delta": _delta(posts24),
            # Alerts raised in the last 24h, and how many of those are critical
            # and still unhandled — the tile shows the first and the tooltip
            # the second, so "12 alerts" never hides "and 4 are untouched".
            "alert_posts": alert_posts,
            "alert_posts_delta": _delta(alerts24),
            "critical_alerts_open": open_critical,
            "fake_pr_campaigns": fake_pr_campaigns,
            "unverified_rumours": unverified_rumours,
            "platforms_online": sum(1 for p in platforms if p["online"]),
            "platforms_total": len(platforms),
        },
        "sparklines": {
            "posts": _hour_buckets(posts24, 24),
            "threats": _hour_buckets(flagged24, 24),
            "alerts": _hour_buckets(alerts24, 24, key=lambda a: 1),
        },
        "sentiment_distribution": dict(Counter(p.sentiment_label for p in posts24)),
        "sentiment_24h": sentiment_24h,
        "platform_activity": platform_activity,
        "platforms": platforms,
        "accuracy": {
            "overall": round(correct / len(labeled) * 100, 1) if labeled else None,
            "per_class": per_class,
            "sample": len(labeled),
        },
        "last_updated": now.isoformat() + "Z",
    }



@router.get("/models")
def models() -> dict:
    """Live metadata for the 3-model consensus ensemble + threat model —
    architecture, training data and measured accuracy (read from eval reports)."""
    from app.services.model_info import get_models

    return get_models()


@router.get("/emerging")
def emerging(hours: int = 24, limit: int = 40, offset: int = 0,
             platform: str = "", location: str = "", sentiment: str = "",
             min_priority: float = 0.0, min_spread: float = 0.0) -> dict:
    """Alarming claims from a single, uncorroborated source — flagged for police
    to check before a possible rumour goes viral.

    Paged and filterable so the dashboard can show the top few while the
    dedicated review page walks the whole set.

    `min_spread` is the old name for `min_priority` and is still accepted: the
    triage page writes its filters into the URL precisely so a view can be
    handed to the next shift as a link, and those links outlive a rename.
    """
    return detect_emerging(
        hours=max(1, min(hours, 168)),
        limit=max(1, min(limit, 200)), offset=max(0, offset),
        platform=platform, location=location, sentiment=sentiment,
        min_priority=max(0.0, min(min_priority or min_spread, 100.0)),
    )
