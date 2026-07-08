"""Trend analytics: sliding-window hashtag/keyword counts with z-score spike
detection, language breakdown and regional threat heat."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev

from sqlmodel import select

from app.data.templates import CITIES
from app.database import session_scope
from app.models import Post


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _spike_z(series: list[int]) -> float:
    """z-score of the latest bucket vs the preceding ones."""
    if len(series) < 4:
        return 0.0
    prev, last = series[:-1], series[-1]
    mu, sd = mean(prev), pstdev(prev)
    return round((last - mu) / (sd + 0.75), 2)


def _term_stats(posts: list[Post], hours: int, getter) -> list[dict]:
    now = _now()
    buckets = min(hours, 24)
    bucket_len = hours / buckets
    counts: Counter = Counter()
    series: dict[str, list[int]] = defaultdict(lambda: [0] * buckets)
    labels: dict[str, Counter] = defaultdict(Counter)
    for p in posts:
        age = max(0, int((now - p.created_at).total_seconds() // (bucket_len * 3600)))
        idx = buckets - 1 - min(buckets - 1, age)  # oldest → newest
        for term in getter(p) or []:
            t = str(term).strip().lstrip("#")
            if not t:
                continue
            counts[t] += 1
            series[t][idx] += 1
            labels[t][p.threat_label] += 1

    out = []
    for term, count in counts.most_common(14):
        s = series[term]
        half = max(1, len(s) // 2)
        prev_half, last_half = sum(s[:half]), sum(s[half:])
        change = round(((last_half - prev_half) / max(prev_half, 1)) * 100)
        z = _spike_z(s)
        top_label = labels[term].most_common(1)[0][0]
        out.append({
            "term": term, "count": count, "series": s,
            "change_pct": change, "spike_z": z, "spiking": z >= 2.0,
            "top_label": top_label,
        })
    return out


def get_trends(hours: int = 24) -> dict:
    since = _now() - timedelta(hours=hours)
    with session_scope() as s:
        posts = s.exec(select(Post).where(Post.created_at >= since)).all()

    lang_counts = Counter(p.language for p in posts)
    total = len(posts) or 1
    languages = [
        {"name": lang, "count": c, "pct": round(c * 100 / total, 1)}
        for lang, c in lang_counts.most_common()
    ]

    region_posts: dict[str, list[Post]] = defaultdict(list)
    for p in posts:
        if p.location:
            region_posts[p.location].append(p)
    regions = []
    for name, ps in region_posts.items():
        lat, lon = CITIES.get(name, (0.0, 0.0))
        regions.append({
            "name": name, "count": len(ps),
            "avg_threat": round(mean(p.threat_score for p in ps), 1),
            "threats": sum(1 for p in ps if p.threat_label != "Neutral"),
            "lat": lat, "lon": lon,
        })
    regions.sort(key=lambda r: -r["avg_threat"])

    return {
        "window_hours": hours,
        "total_posts": len(posts),
        "hashtags": _term_stats(posts, hours, lambda p: p.hashtags),
        "keywords": _term_stats(posts, hours, lambda p: p.keywords),
        "languages": languages,
        "regions": regions,
    }
