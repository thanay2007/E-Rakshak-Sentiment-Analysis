"""Account-interaction network + coordinated/bot-like amplification detection.

Detection is generic (works on real API data, not just the simulator):
  1. Near-duplicate clustering — word-3-gram Jaccard similarity with
     union-find over recent non-neutral posts (MinHash-style shingling,
     exact because windows are small).
  2. Cluster scoring — synchronized posting (tight time spread), young
     accounts, tiny follower counts, templated handle prefixes.
  3. Output — flagged clusters with a confidence score and human-readable
     "why flagged" evidence, plus a force-graph (nodes sized by centrality,
     colored by threat contribution).
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

import networkx as nx
from sqlmodel import select

from app.database import session_scope
from app.models import Post
from app.ml.normalize import normalize


def _shingles(text: str, n: int = 3) -> set:
    words = normalize(text).split()
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _detect_clusters(posts: list[Post]) -> list[list[Post]]:
    """Near-duplicate clustering over non-neutral posts (capped for O(n²))."""
    candidates = [p for p in posts if p.threat_label != "Neutral"][:400]
    if len(candidates) < 2:
        return []
    sh = [_shingles(p.text) for p in candidates]
    uf = _UnionFind(len(candidates))
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if _jaccard(sh[i], sh[j]) >= 0.55:
                uf.union(i, j)
    groups: dict[int, list[Post]] = defaultdict(list)
    for i, p in enumerate(candidates):
        groups[uf.find(i)].append(p)
    return [g for g in groups.values() if len({p.author_handle for p in g}) >= 3]


def _common_prefix_ratio(handles: list[str]) -> float:
    """Share of handles matching the most common 6+ char prefix (templated names)."""
    if len(handles) < 3:
        return 0.0
    prefixes = Counter(h[:8] for h in handles if len(h) >= 8)
    if not prefixes:
        return 0.0
    _, n = prefixes.most_common(1)[0]
    return n / len(handles)


def _score_cluster(group: list[Post]) -> tuple[float, list[str]]:
    handles = sorted({p.author_handle for p in group})
    times = [p.created_at for p in group]
    spread = (max(times) - min(times)).total_seconds()
    ages = [p.author_account_age_days for p in group]
    followers = [p.author_followers for p in group]
    prefix_r = _common_prefix_ratio(handles)

    confidence, why = 0.30, []
    why.append(f"{len(handles)} accounts posted near-identical text "
               f"({len(group)} posts within {int(spread // 60)}m {int(spread % 60)}s)")
    if len(handles) >= 5:
        confidence += 0.18
    if spread <= 600:
        confidence += 0.20
        why.append("posting times synchronized inside a 10-minute window")
    if mean(ages) < 90:
        confidence += 0.15
        why.append(f"average account age only {int(mean(ages))} days")
    if mean(followers) < 150:
        confidence += 0.10
        why.append(f"average follower count only {int(mean(followers))}")
    if prefix_r >= 0.5:
        confidence += 0.12
        why.append(f"handles share a templated prefix pattern ({handles[0][:8]}…)")
    return round(min(confidence, 0.98), 2), why


def get_network(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    with session_scope() as s:
        posts = s.exec(select(Post).where(Post.created_at >= since)).all()

    clusters_raw = _detect_clusters(posts)

    # ── flagged clusters ─────────────────────────────────────────────────
    clusters, bot_handles, cluster_of = [], set(), {}
    for i, group in enumerate(sorted(clusters_raw, key=len, reverse=True)):
        confidence, why = _score_cluster(group)
        handles = sorted({p.author_handle for p in group})
        cid = f"C{i + 1}"
        for h in handles:
            cluster_of[h] = cid
        if confidence >= 0.65:
            bot_handles.update(handles)
        label_counts = Counter(p.threat_label for p in group)
        clusters.append({
            "id": cid,
            "label": label_counts.most_common(1)[0][0],
            "confidence": confidence,
            "accounts": handles,
            "posts": len(group),
            "why": why,
            "sample_text": (group[0].translation or group[0].text)[:180],
            "avg_threat": round(mean(p.threat_score for p in group), 1),
        })

    # ── graph ────────────────────────────────────────────────────────────
    by_author: dict[str, list[Post]] = defaultdict(list)
    for p in posts:
        by_author[p.author_handle].append(p)

    # keep the most interesting authors: all cluster members + top by threat activity
    ranked = sorted(by_author.items(),
                    key=lambda kv: (kv[0] in cluster_of,
                                    max(p.threat_score for p in kv[1]),
                                    len(kv[1])),
                    reverse=True)
    keep = {h for h, _ in ranked[:80]} | set(cluster_of)

    G = nx.Graph()
    for h in keep:
        G.add_node(h)

    # coordination edges: members of the same detected cluster
    for c in clusters:
        acc = [a for a in c["accounts"] if a in keep]
        for i in range(len(acc)):
            for j in range(i + 1, len(acc)):
                w = G.get_edge_data(acc[i], acc[j], {}).get("weight", 0)
                G.add_edge(acc[i], acc[j], weight=w + 2, kind="coordination")

    # hashtag affinity edges (weaker signal, capped)
    tag_authors: dict[str, set[str]] = defaultdict(set)
    for p in posts:
        if p.author_handle in keep:
            for t in (p.hashtags or [])[:4]:
                tag_authors[t].add(p.author_handle)
    edge_budget = 260 - G.number_of_edges()
    for t, authors in sorted(tag_authors.items(), key=lambda kv: -len(kv[1])):
        alist = sorted(authors)[:8]
        for i in range(len(alist)):
            for j in range(i + 1, len(alist)):
                if edge_budget <= 0:
                    break
                if not G.has_edge(alist[i], alist[j]):
                    G.add_edge(alist[i], alist[j], weight=1, kind="hashtag")
                    edge_budget -= 1

    centrality = nx.degree_centrality(G) if G.number_of_nodes() > 1 else {}

    nodes = []
    for h in keep:
        ps = by_author[h]
        p0 = ps[0]
        nodes.append({
            "id": h,
            "label": p0.author_name or h,
            "influence": round(centrality.get(h, 0.0), 4),
            "followers": p0.author_followers,
            "threat": round(mean(p.threat_score for p in ps), 1),
            "posts": len(ps),
            "platform": Counter(p.platform for p in ps).most_common(1)[0][0],
            "is_bot": h in bot_handles,
            "cluster": cluster_of.get(h),
        })

    links = [
        {"source": a, "target": b, "weight": d.get("weight", 1), "kind": d.get("kind", "hashtag")}
        for a, b, d in G.edges(data=True)
    ]

    return {
        "window_hours": hours,
        "nodes": nodes,
        "links": links,
        "clusters": sorted(clusters, key=lambda c: -c["confidence"]),
    }
