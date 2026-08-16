# -*- coding: utf-8 -*-
"""Fake-PR / astroturf campaign detection — scoped to law-and-order impact.

A "fake PR" campaign here means coordinated, INAUTHENTIC messaging engineered to
manufacture a narrative rather than organic public opinion. Both halves of that
sentence have to be established before anything is reported, and getting the
second half wrong is what this module is mostly built to avoid.

Duplication on its own proves nothing. Four things routinely produce identical
copy across "several accounts" with no campaign anywhere in sight:

  • one organisation posting to its own several platforms — @amdavadamc on
    Instagram and @AmdavadAMC on X are the same municipal corporation, and
    counting the handle strings gives two accounts where there is one body
  • a press release syndicated by the desks it was sent to
  • the same post collected twice
  • a stock phrase everyone reaches for on the same day

Every one of those used to come back labelled "Coordinated whitewash / paid
praise", which is an accusation of corruption levelled at, among others, the
Surat City Police announcing an arrest. So the pipeline now establishes who is
actually behind a cluster before it scores it:

  identity      handles are folded to an ACTOR (case and punctuation ignored),
                so one body posting to three platforms counts once
  authenticity  an actor that is platform-verified, or on this deployment's own
                seed roster of official desks, or carries a large established
                audience, is an authentic public voice. A cluster made only of
                those is syndication, and is reported as syndication — visible,
                but never as a campaign
  corroboration a campaign additionally needs at least one signal of
                coordination beyond the shared text: a synchronised burst, a
                bot-heavy roster, throwaway accounts, or the same copy crossing
                platforms under genuinely different actors
  a floor       below `MIN_CONFIDENCE` nothing is reported at all, because a
                weak flag on this screen reads exactly like a strong one

What is left is the thing the tool exists for: a roster of accounts with no
standing, posting the same words within minutes of each other.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

from sqlmodel import select

from app.config import settings
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
#: …but never below this many posts, whatever the ratio works out to. The
#: ratio alone has two failure modes, and both hide exactly what we are looking
#: for: on a small window it lands at the floor of 2, so any phrase shared by
#: three or more accounts — the definition of the thing being detected — is
#: discarded as boilerplate and no cluster forms at all; and on a large window
#: a campaign big enough to exceed 10% of the corpus disqualifies itself.
#: This is a cost guard, not a correctness one — the Jaccard threshold below is
#: what decides whether two posts are actually the same copy — so it can afford
#: to be generous.
_MIN_SHINGLE_CEILING = 25
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

    ceiling = max(_MIN_SHINGLE_CEILING, int(len(cand) * _COMMON_SHINGLE_RATIO))
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
    idx_of: dict[int, list[int]] = defaultdict(list)
    for i, p in enumerate(cand):
        root = uf.find(i)
        groups[root].append(p)
        idx_of[root].append(i)

    out: list[list[Post]] = []
    for root, members in groups.items():
        members = _tighten(members, [sh[i] for i in idx_of[root]])
        # Actors, not handle strings: one organisation posting the same notice
        # to its Instagram and its X account is one voice, not a "cluster of
        # two accounts", and this is the rule that decides whether it is even
        # considered.
        if len({actor_key(p.author_handle) for p in members}) >= min_accounts:
            out.append(members)
    return out


#: A member kept in a cluster has to resemble the cluster's own longest post
#: this much. Union-find is transitive — A~B and B~C put A and C together even
#: when they share nothing — and on a corpus of civic announcements that drift
#: is how unrelated posts end up in one "campaign".
_ANCHOR_SIMILARITY = 0.35


def _tighten(members: list[Post], shingles: list[set]) -> list[Post]:
    """Drop cluster members that only reached it through a chain."""
    if len(members) < 3:
        return members
    anchor = max(range(len(members)), key=lambda i: len(shingles[i]))
    kept = [(p, sh) for i, (p, sh) in enumerate(zip(members, shingles))
            if i == anchor or _jaccard(shingles[anchor], sh) >= _ANCHOR_SIMILARITY]
    return [p for p, _sh in kept]


# ── who is actually behind a cluster ───────────────────────────────────────

def actor_key(handle: str) -> str:
    """Fold a handle to the body behind it.

    Case and punctuation carry no identity: @amdavadamc, @AmdavadAMC and
    @Amdavad_AMC are one municipal corporation posting to three platforms, and
    the detector's minimum-account rule is meaningless if they count as three
    accounts.
    """
    return re.sub(r"[^a-z0-9]", "", (handle or "").lower())


def _seed_actors() -> set[str]:
    """Actors this deployment itself declares to be official desks.

    Everything in the seed configuration is a municipal corporation, police
    commissionerate, district desk or news wire that SENTINEL was pointed at
    deliberately. They are the sources, not the suspects.
    """
    seeds: set[str] = set()
    try:
        for handle, _city in settings.IG_SEED_USERNAMES:
            seeds.add(actor_key(handle))
        for handle, _city in settings.FB_PAGE_IDS:
            seeds.add(actor_key(handle))
        for handle, _city in settings.TELEGRAM_CHANNELS:
            seeds.add(actor_key(handle))
    except Exception:                       # malformed config must not break detection
        log.warning("could not read the seed roster for PR analysis", exc_info=True)
    return seeds


#: An audience this size is not something a sockpuppet farm assembles for a
#: campaign — it takes years and is the strongest available evidence that an
#: account is a real public voice, verified flag or not. (Several of the police
#: pages here carry no verified flag on the platform the crawler reads them
#: from, while having half a million followers.)
_ESTABLISHED_FOLLOWERS = 25_000
#: Or a smaller audience held for a long time.
_ESTABLISHED_AGE_DAYS = 730
_ESTABLISHED_AGE_FOLLOWERS = 2_000


class _Actor:
    """One body behind a cluster, merged across its handles and platforms."""

    def __init__(self, key: str):
        self.key = key
        self.handles: set[str] = set()
        self.platforms: set[str] = set()
        self.followers = 0
        self.age_days = 0
        self.verified = False
        self.name = ""
        self.posts = 0

    def add(self, p: Post) -> None:
        self.handles.add(p.author_handle)
        if p.platform:
            self.platforms.add(p.platform)
        self.followers = max(self.followers, p.author_followers or 0)
        self.age_days = max(self.age_days, p.author_account_age_days or 0)
        self.verified = self.verified or bool(p.author_verified)
        self.name = self.name or (getattr(p, "author_name", "") or "")
        self.posts += 1

    def established(self, seeds: set[str]) -> tuple[bool, str]:
        if self.verified:
            return True, "platform-verified"
        if self.key in seeds:
            return True, "monitored official desk"
        if self.followers >= _ESTABLISHED_FOLLOWERS:
            return True, f"{self.followers:,} followers"
        if self.age_days >= _ESTABLISHED_AGE_DAYS and self.followers >= _ESTABLISHED_AGE_FOLLOWERS:
            return True, f"{self.age_days // 365}-year-old account with {self.followers:,} followers"
        return False, ""


def _actors(group: list[Post]) -> dict[str, _Actor]:
    out: dict[str, _Actor] = {}
    for p in group:
        key = actor_key(p.author_handle)
        if not key:
            continue
        out.setdefault(key, _Actor(key)).add(p)
    return out


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
    # Was "Coordinated whitewash / paid praise". Nothing measured here
    # establishes that anyone was paid, and the clusters that landed under this
    # heading were mostly civic desks announcing their own work.
    "image_whitewash": "Coordinated praise campaign",
    "narrative_push": "Coordinated narrative push",
}

#: Nothing below this is shown. A cluster that clears the structural gates but
#: has no corroborating signal is duplication, and duplication is not a
#: campaign; putting it on screen at 30% next to a real one at 80% invites the
#: reader to treat both as findings.
MIN_CONFIDENCE = 0.45


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
    seeds = _seed_actors()
    neutral_clusters = 0
    syndication: list[dict] = []
    weak_clusters = 0
    campaigns = []
    for idx, group in enumerate(sorted(clusters, key=len, reverse=True)):
        labels = Counter(p.sentiment_label for p in group)
        # Scope filter: a coordinated cluster of neutral logistics posts is a
        # marketing schedule, not something this console should surface.
        if labels.most_common(1)[0][0] == "neutral":
            neutral_clusters += 1
            continue

        handles = sorted({p.author_handle for p in group})
        actors = _actors(group)
        established = {k: a.established(seeds) for k, a in actors.items()}
        independent = [k for k, (is_est, _why) in established.items() if not is_est]
        platforms = sorted({p.platform for p in group if p.platform})
        times = [p.created_at for p in group]
        spread = (max(times) - min(times)).total_seconds()
        lean, uniformity = _sentiment_lean(group)

        # ── the authenticity gate ──────────────────────────────────────────
        # A campaign needs a roster that could plausibly be one. Verified
        # accounts, this deployment's own seed desks and accounts carrying a
        # large established audience are authentic public voices; several of
        # them running the same copy is syndication, which is worth seeing and
        # is not worth accusing anyone over.
        if len(independent) < min_accounts:
            syndication.append({
                "id": f"SYN{len(syndication) + 1}",
                "accounts": handles,
                "actors": len(actors),
                "posts": len(group),
                "platforms": platforms,
                "sentiment_lean": lean,
                "sample_text": (group[0].translation or group[0].text)[:180],
                "first_seen": min(times).isoformat() + "Z",
                "why": _syndication_reason(actors, established, min_accounts),
            })
            continue

        ages = [actors[k].age_days for k in independent]
        followers = [actors[k].followers for k in independent]

        # Scored per actor, not per post: a roster of three where one posted ten
        # times is three accounts' worth of evidence, not twelve.
        scores = [score_account(sorted(actors[k].handles)[0],
                                name=actors[k].name,
                                followers=actors[k].followers,
                                account_age_days=actors[k].age_days,
                                verified=actors[k].verified)["score"]
                  for k in independent]
        bot_ratio = round(sum(s >= 60 for s in scores) / len(scores), 2)
        suspicious_ratio = round(sum(s >= 35 for s in scores) / len(scores), 2)
        ctype = _campaign_type(group, lean)

        # Actors on more than one platform each — the same body posting to its
        # own two accounts is not distribution, so cross-platform only counts
        # when genuinely different actors carry the same copy.
        multi_actor_platforms = len(platforms) > 1 and len({
            p for k in independent for p in actors[k].platforms}) > 1 and len(independent) > 1

        why: list[str] = []
        corroborated = False
        # The duplication itself, weighted by how many independent voices it
        # took — three accounts sharing a phrase is common, ten is not.
        conf = 0.10 + min(0.30, 0.05 * len(independent))
        why.append(f"{len(independent)} independent account(s) with no established "
                   f"audience posted near-identical copy ({len(group)} posts)")
        anchor_words = max(len((p.text or "").split()) for p in group)
        if anchor_words >= 40:
            conf += 0.08
            why.append(f"the shared text runs to {anchor_words} words — far past "
                       f"a phrase people land on independently")
        if spread <= 900:
            conf += 0.22
            corroborated = True
            why.append(f"synchronized within {int(spread // 60)} minutes")
        elif spread <= 3600:
            conf += 0.12
            corroborated = True
            why.append(f"posted inside one hour of each other")
        if bot_ratio >= 0.4:
            conf += 0.20
            corroborated = True
            why.append(f"{int(bot_ratio * 100)}% of the roster scores as likely bots")
        elif suspicious_ratio >= 0.5:
            conf += 0.10
            corroborated = True
            why.append(f"{int(suspicious_ratio * 100)}% of the roster carries "
                       f"automation signals (throwaway handles, tiny audiences)")
        if uniformity >= 0.8:
            conf += 0.10
            why.append(f"{int(uniformity * 100)}% share the same {lean} framing "
                       f"(engineered, not organic debate)")
        if ages and mean(ages) < 90:
            conf += 0.12
            corroborated = True
            why.append(f"average account age only {int(mean(ages))} days")
        if followers and mean(followers) < 150:
            conf += 0.10
            corroborated = True
            why.append(f"average follower count only {int(mean(followers))}")
        amplified = sum(p.is_amplified for p in group)
        if amplified:
            conf += 0.05
            why.append(f"{amplified} posts flagged as paid/boosted amplification")
        if multi_actor_platforms:
            # Identical copy appearing on several platforms at once, under
            # different actors, is not how a message spreads organically.
            conf += 0.10
            corroborated = True
            why.append(f"same copy posted across {len(platforms)} platforms "
                       f"({', '.join(platforms)}) by different accounts")

        # ── the corroboration gate ─────────────────────────────────────────
        # Shared words plus matching sentiment describes every crowd that
        # agrees about something. Reporting needs at least one signal that the
        # posting itself was organised.
        confidence = round(min(conf, 0.98), 2)
        if not corroborated or confidence < MIN_CONFIDENCE:
            weak_clusters += 1
            continue

        reach = sum((p.engagement or {}).get("shares", 0) +
                    (p.engagement or {}).get("views", 0) for p in group)
        top_hashtags = Counter(t for p in group for t in (p.hashtags or [])).most_common(4)

        campaigns.append({
            "id": f"PR{idx + 1}",
            "type": ctype,
            "type_label": _TYPE_LABEL[ctype],
            "confidence": confidence,
            "law_order_category": labels.most_common(1)[0][0],
            "accounts": handles,
            "account_count": len(independent),
            "handle_count": len(handles),
            "established_accounts": sorted(
                h for k, (is_est, _w) in established.items() if is_est
                for h in actors[k].handles),
            "posts": len(group),
            "bot_ratio": bot_ratio,
            "suspicious_ratio": suspicious_ratio,
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
        # this window", not as "the detector did not run" — and so that every
        # cluster the detector saw is accounted for somewhere, rather than
        # silently dropped.
        "posts_scanned": len(posts),
        "clusters_found": len(clusters),
        "neutral_clusters_ignored": neutral_clusters,
        "syndication_ignored": len(syndication),
        "syndication": syndication[:12],
        "weak_clusters_ignored": weak_clusters,
        "min_accounts": min_accounts,
        "min_confidence": MIN_CONFIDENCE,
        "note": (f"A campaign here is ≥{min_accounts} independent accounts — the same "
                 "organisation's handles count once — posting near-identical copy, "
                 "with at least one further sign of coordination (a synchronised "
                 "burst, a bot-heavy roster, throwaway accounts, or the copy "
                 "crossing platforms). Official desks and verified accounts "
                 "re-posting the same notice are listed separately as syndication."),
    }


def _syndication_reason(actors: dict, established: dict, min_accounts: int) -> str:
    """Why a duplicate-copy cluster is not being called a campaign."""
    if len(actors) < min_accounts:
        names = ", ".join(sorted({h for a in actors.values() for h in a.handles}))
        return (f"One organisation posting to its own accounts ({names}) — "
                f"{len(actors)} independent voice(s), not {min_accounts}.")
    reasons = sorted({why for _is_est, why in established.values() if why})
    return ("Every account in this cluster is an established public voice ("
            + "; ".join(reasons) + ") — a press release being syndicated, not "
            "an inauthentic push.")


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
