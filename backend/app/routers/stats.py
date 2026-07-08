"""GET /api/stats — every number the dashboard KPIs and overview charts need,
including LIVE classification accuracy against simulated ground truth."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlmodel import func, select

from app.crawlers.registry import platform_status
from app.database import session_scope
from app.models import Alert, Post

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
def get_stats() -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since24 = now - timedelta(hours=24)
    with session_scope() as s:
        total_posts = s.exec(select(func.count()).select_from(Post)).one()
        posts24 = s.exec(select(Post).where(Post.created_at >= since24)).all()
        alerts24 = s.exec(select(Alert).where(Alert.created_at >= since24)).all()
        open_critical = s.exec(
            select(func.count()).select_from(Alert)
            .where(Alert.severity == "critical", Alert.status == "new")
        ).one()

    threats24 = [p for p in posts24 if p.threat_score >= 50]
    campaigns = len({p.cluster_id for p in posts24 if p.cluster_id})
    platforms = platform_status()

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
    platform_threats = Counter(p.platform for p in threats24)
    platform_activity = [
        {"platform": pf, "posts": c, "threats": platform_threats.get(pf, 0)}
        for pf, c in platform_counts.most_common()
    ]

    # Live classification accuracy vs simulated ground truth
    labeled = [p for p in posts24 if p.true_label]
    correct = sum(1 for p in labeled if p.threat_label == p.true_label)
    per_class = {}
    for lbl in ["Incitement to Violence", "Inflammatory", "Fake News", "Neutral"]:
        cls = [p for p in labeled if p.true_label == lbl]
        if cls:
            per_class[lbl] = round(sum(1 for p in cls if p.threat_label == lbl) / len(cls) * 100, 1)

    return {
        "kpis": {
            "posts_monitored": total_posts,
            "posts_monitored_delta": _delta(posts24),
            "active_threats": len(threats24),
            "active_threats_delta": _delta(threats24),
            "critical_alerts": open_critical,
            "critical_alerts_delta": _delta([a for a in alerts24 if a.severity == "critical"]),
            "platforms_online": sum(1 for p in platforms if p["online"]),
            "platforms_total": len(platforms),
            "campaigns": campaigns,
        },
        "sparklines": {
            "posts": _hour_buckets(posts24, 24),
            "threats": _hour_buckets(threats24, 24),
            "alerts": _hour_buckets(alerts24, 24, key=lambda a: 1),
        },
        "threat_distribution": dict(Counter(p.threat_label for p in posts24)),
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
