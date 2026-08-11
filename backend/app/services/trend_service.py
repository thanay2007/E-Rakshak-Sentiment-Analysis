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


def _term_stats(posts: list[Post], hours: int, getter, kind: str) -> list[dict]:
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
            labels[t][p.sentiment_label] += 1

    out = []
    
    # Auto-discovery: terms that are both spiking AND trending negative
    spiking_negative = []

    for term, count in counts.most_common(14):
        s = series[term]
        half = max(1, len(s) // 2)
        prev_half, last_half = sum(s[:half]), sum(s[half:])
        change = round(((last_half - prev_half) / max(prev_half, 1)) * 100)
        z = _spike_z(s)
        top_label = labels[term].most_common(1)[0][0]
        spiking = z >= 2.0
        
        if spiking and top_label == "negative":
            spiking_negative.append({"kind": kind, "value": term})

        out.append({
            "term": term, "count": count, "series": s,
            "change_pct": change, "spike_z": z, "spiking": spiking,
            "top_label": top_label,
        })
        
    if spiking_negative:
        from app.models import WatchlistItem
        with session_scope() as s:
            existing = {w.value for w in s.exec(select(WatchlistItem)).all()}
            for st in spiking_negative:
                if st["value"] not in existing:
                    w = WatchlistItem(kind=st["kind"], value=st["value"], note="Auto-discovered due to threat spike", active=False)
                    s.add(w)
            s.commit()
            
    return out


def get_trends(hours: int = 24) -> dict:
    since = _now() - timedelta(hours=hours)
    with session_scope() as s:
        # Seven of thirty-eight columns. The rest — post text, its translation,
        # the class probability vector, evidence reports — are never read here
        # and every one of them would cross the network from a database that
        # may be in another region. Rows still support attribute access, so
        # nothing below changes.
        posts = s.exec(
            select(Post.created_at, Post.language, Post.location,
                   Post.hashtags, Post.keywords, Post.sentiment_label,
                   Post.concern_score)
            .where(Post.created_at >= since)
        ).all()

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
            "avg_concern": round(mean(p.concern_score for p in ps), 1),
            "threats": sum(1 for p in ps if p.sentiment_label == "negative"),
            "lat": lat, "lon": lon,
        })
    regions.sort(key=lambda r: -r["avg_concern"])

    return {
        "window_hours": hours,
        "total_posts": len(posts),
        "hashtags": _term_stats(posts, hours, lambda p: p.hashtags, "hashtag"),
        "keywords": _term_stats(posts, hours, lambda p: p.keywords, "keyword"),
        "languages": languages,
        "regions": regions,
    }
