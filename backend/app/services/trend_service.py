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

    for term, count in counts.most_common(14):
        s = series[term]
        half = max(1, len(s) // 2)
        prev_half, last_half = sum(s[:half]), sum(s[half:])
        change = round(((last_half - prev_half) / max(prev_half, 1)) * 100)
        z = _spike_z(s)
        top_label = labels[term].most_common(1)[0][0]
        spiking = z >= 2.0
        sentiment_mix = dict(labels[term])

        out.append({
            "term": term, "kind": kind, "count": count, "series": s,
            "change_pct": change, "spike_z": z, "spiking": spiking,
            "top_label": top_label, "sentiment_mix": sentiment_mix,
            "negative_share": round(
                sentiment_mix.get("negative", 0) / max(count, 1), 2),
        })

    return out


def _bucketed_sentiment(posts: list, hours: int) -> list[dict]:
    """Sentiment counts per time bucket, on the same grid as the term series."""
    now = _now()
    buckets = min(hours, 24)
    bucket_len = hours / buckets
    grid = [{"positive": 0, "neutral": 0, "negative": 0, "concern_sum": 0.0, "n": 0}
            for _ in range(buckets)]
    for p in posts:
        age = max(0, int((now - p.created_at).total_seconds() // (bucket_len * 3600)))
        idx = buckets - 1 - min(buckets - 1, age)
        cell = grid[idx]
        if p.sentiment_label in cell:
            cell[p.sentiment_label] += 1
        cell["concern_sum"] += p.concern_score or 0
        cell["n"] += 1

    out = []
    for i, cell in enumerate(grid):
        start = now - timedelta(hours=bucket_len * (buckets - i))
        out.append({
            "label": start.strftime("%H:%M" if bucket_len < 24 else "%d %b"),
            "positive": cell["positive"], "neutral": cell["neutral"],
            "negative": cell["negative"],
            "total": cell["n"],
            "avg_concern": round(cell["concern_sum"] / cell["n"], 1) if cell["n"] else 0.0,
        })
    return out


def watch_suggestions(hours: int = 24) -> list[dict]:
    """Spiking negative terms an analyst may want to start watching.

    This used to be a side effect of *rendering the trends page*: every poll
    inserted WatchlistItem rows. A GET that writes is bad enough on its own, but
    it also meant the watchlist silently grew rules nobody chose, from any
    dashboard left open. Now the same terms are offered as suggestions and only
    become rules when an analyst accepts one.
    """
    from app.models import WatchlistItem

    data = get_trends(hours)
    with session_scope() as s:
        existing = {(w.kind, w.value.lower())
                    for w in s.exec(select(WatchlistItem)).all()}

    out = []
    for t in data["hashtags"] + data["keywords"]:
        if not t["spiking"] or t["top_label"] != "negative":
            continue
        if (t["kind"], t["term"].lower()) in existing:
            continue
        out.append({
            "kind": t["kind"], "value": t["term"], "count": t["count"],
            "spike_z": t["spike_z"], "change_pct": t["change_pct"],
            "negative_share": t["negative_share"],
            "reason": (f"{t['count']} posts, {t['spike_z']}σ above its own baseline, "
                       f"{int(t['negative_share'] * 100)}% negative"),
        })
    out.sort(key=lambda x: -x["spike_z"])
    return out[:12]


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
                   Post.concern_score, Post.platform)
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

    platform_rows: dict[str, list] = defaultdict(list)
    for p in posts:
        if p.platform:
            platform_rows[p.platform].append(p)
    platforms = sorted(
        ({"name": name,
          "count": len(ps),
          "negative": sum(1 for q in ps if q.sentiment_label == "negative"),
          "positive": sum(1 for q in ps if q.sentiment_label == "positive"),
          "avg_concern": round(mean(q.concern_score for q in ps), 1)}
         for name, ps in platform_rows.items()),
        key=lambda r: -r["count"])

    sentiment_counts = Counter(p.sentiment_label for p in posts)
    return {
        "window_hours": hours,
        "total_posts": len(posts),
        "hashtags": _term_stats(posts, hours, lambda p: p.hashtags, "hashtag"),
        "keywords": _term_stats(posts, hours, lambda p: p.keywords, "keyword"),
        "languages": languages,
        "regions": regions,
        "platforms": platforms,
        "sentiment_series": _bucketed_sentiment(posts, hours),
        "sentiment_totals": {
            "positive": sentiment_counts.get("positive", 0),
            "neutral": sentiment_counts.get("neutral", 0),
            "negative": sentiment_counts.get("negative", 0),
        },
        "avg_concern": round(mean([p.concern_score for p in posts]), 1) if posts else 0.0,
    }
