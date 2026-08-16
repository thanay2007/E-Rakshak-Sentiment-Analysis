# -*- coding: utf-8 -*-
"""Emerging-but-unverified detection.

The scenario the mentor described: a post makes an alarming claim and ONLY ONE
channel has posted it so far — no independent source has corroborated it, so we
cannot yet call it fake or real. Those are the posts police most need flagged
*early*: if it's a fabricated rumour, this is the window to act before it goes
viral.

A post is flagged EMERGING-UNVERIFIED when all five hold:
  1. Not an established channel — the author is unverified, below
     ESTABLISHED_FOLLOWERS, and is not posting at broadcast volume. A news desk
     is what *corroborates* a claim, so it cannot also be the uncorroborated
     claim.
  2. It actually makes a claim — see `_claim_check`. A reel caption, a wall of
     hashtags or a line of praise asserts nothing that could be checked, and a
     triage queue full of those is a queue nobody opens.
  3. Alarming — concern score at or above CONCERN_FLOOR.
  4. Single-source — no other distinct account in the window has posted a
     near-identical claim (word-3-gram Jaccard ≥ 0.5). "Only one channel."
  5. Not corroborated — the cross-source fact-check found no independent news
     coverage (or was never able to corroborate it).

Every one of those is a filter *against* the queue, and that is the point: this
list is only useful if being on it means something. The queue has now failed in
both directions and the fixes for each are load-bearing:

  * An early version scored spread as `0.02 × followers` and waived the spread
    test for anything negative, so a wire agency's routine bulletin outranked a
    post being frantically reshared and the queue grew to 260 items — mostly
    national newspapers and the police's own account, filed as unverified
    rumours.
  * Its replacement ranked on raw interaction volume, which on live data meant
    *view counts*, because views are the only engagement number most of these
    adapters can read. Instagram serves a million views on a reel the algorithm
    pushed, so the top of the queue became a reel captioned "મારો જીવ 💕" with
    twenty hashtags and a Turkish soap-opera promo — neither of which is a
    claim, let alone an unverified one. Views are distribution, not
    propagation: they say the platform showed the post to people, not that
    anybody repeated it. They are now a small, capped term.

Ranking is by `priority_score`, which is *not* a spread measure and no longer
pretends to be. Across live data almost no post carries usable share/comment
counts, so a spread number would be zero for every genuine candidate and large
for exactly the algorithmic content that does not belong here. What the score
weighs instead is how alarming the claim is, whether it carries the phrasing
rumours use, and — where the numbers exist at all — how much it is being passed
on. Each flagged item ships with a plain-English reason, and the counts of what
was filtered out are returned alongside so a short queue is legible rather than
suspicious. Computed live (not stored) so it always reflects the current window.
"""
from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlmodel import select

from app.database import session_scope
from app.models import Post
from app.services.network_service import _jaccard, _shingles

SIM_THRESHOLD = 0.5      # near-duplicate similarity
MAX_SCAN = 1500

#: A post has to be *alarming* to be worth a triage slot. Sits well above the
#: median concern of the live corpus (4) and above its p90 (34): this admits
#: the genuinely hostile tail rather than the day's news. It was 25, which let
#: in a heart-emoji reel (28) and a drama promo (29) — both scoring there on
#: nothing but the model's uncertainty about non-English text.
CONCERN_FLOOR = 40

#: Interactions needed before an engagement *rate* means anything. Eleven likes
#: on a seventy-follower account is a 15% rate, which is not virality — it is a
#: small denominator. Without this floor those posts outrank real spread.
MIN_INTERACTIONS_FOR_RATE = 50

#: An engagement rate this far above the author's own audience reads as the
#: post outrunning the account that made it.
EXCEPTIONAL_RATE = 0.05

#: Verified, or this many followers: an established channel. Such an account is
#: what *corroborates* a claim — it is not the "one obscure channel nobody has
#: confirmed" this queue exists to catch. Their posts are still scored, alerted
#: and searchable everywhere else in the console; they are only kept out of the
#: rumour queue, and the count of them is reported so the omission is visible.
ESTABLISHED_FOLLOWERS = 100_000

#: Posts in the scanned window above which an account is a *publisher*, not a
#: source. This exists because the follower test cannot do the job alone: on
#: live data the X adapter reads no follower count at all, so @IndianExpress
#: (159 posts in the window) and @akilanews (118) both arrive with
#: `author_followers = 0` and sail through `_is_established` into a rumour
#: queue. Volume is the signal the data actually carries, it needs no
#: maintained list of outlet names, and it says the right thing: an account
#: filing a hundred stories a week is a channel, and a channel is what
#: corroborates a claim rather than being one. Genuine candidates in the same
#: window post three to five times.
BROADCAST_POSTS_IN_WINDOW = 12

#: Words a post needs, once hashtags, links and @mentions are removed, before
#: it can be said to claim anything. Eight is roughly a sentence — enough to
#: assert something an officer could go and check.
MIN_CLAIM_WORDS = 8

# A phrase carried by more than this share of the window is boilerplate and
# would make every post "corroborate" every other one.
_COMMON_SHINGLE_RATIO = 0.10

#: How strongly a post's speech act suggests a rumour rather than a report.
#: `intent` comes from lexicon matching (ml/classifier.py): "rumor" means the
#: post carries the phrasing rumours are built from — "forward before it's
#: deleted", "the media won't show you this".
_INTENT_WEIGHT = {"rumor": 1.0, "call_to_action": 0.6, "opinion": 0.2}

_HASHTAG_RE = re.compile(r"#\S+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MENTION_RE = re.compile(r"@[\w_]+")


def _body_words(text: str) -> list[str]:
    """What the author actually wrote, minus tags, links and mentions.

    A word is a whitespace-separated token carrying at least two letters or
    combining marks. Both halves of that are load-bearing:

      * digits, punctuation and emoji are not letters, so "₹100 !!! 🔥🔥" is
        correctly nothing to check;
      * marks count, because Gujarati and Devanagari vowel signs are Unicode
        category Mn and Python's `\\w` excludes them. A `[^\\W\\d_]{2,}` pattern
        therefore shatters "સુરત સિવિલ હોસ્પિટલમાં" into "રત", "ટલમ" — it does
        not merely miscount, it makes long Gujarati posts look like they have
        too little text to be a claim, and silently drops the local-language
        grievances this queue exists to surface.
    """
    stripped = _HASHTAG_RE.sub(" ", _MENTION_RE.sub(" ", _URL_RE.sub(" ", text or "")))
    words = []
    for token in stripped.split():
        letters = sum(1 for ch in token
                      if unicodedata.category(ch)[0] in ("L", "M"))
        if letters >= 2:
            words.append(token)
    return words


def _claim_check(p: Post) -> str:
    """"" if the post makes a checkable claim, else why it does not.

    Three ways a post fails, and each was in the queue before this existed:

      * praise — a rumour queue does not contain approval. The post an officer
        is being asked to check before it goes viral is never "great work by
        the police team".
      * too little text — "મારો જીવ 💕🔐🧿" asserts nothing. It was the top of
        the queue at 82/100 on 1.9M algorithmic views.
      * more hashtags than words — the shape of a reel caption reaching for
        distribution, not of somebody reporting something.
    """
    if p.sentiment_label == "positive":
        return "praise"
    words = _body_words(p.text)
    if len(words) < MIN_CLAIM_WORDS:
        return "no substantive text"
    if len(p.hashtags or []) > len(words):
        return "hashtag-led caption"
    return ""


@lru_cache(maxsize=1)
def _seed_handles() -> frozenset[str]:
    """Every account this deployment *configured* as a source, case-folded.

    A handle in .env is there because somebody decided it is an official desk
    worth reading — a municipal corporation, a police account, a news channel,
    a party's own feed. That is the definition of an established channel, and
    it holds where the follower count does not: @aapgujaratofficial arrives
    from the Telegram adapter with no follower count at all and would otherwise
    file its press releases in the rumour queue.

    Only *configured* seeds. Accounts found by discovery are deliberately kept
    in: discovery goes looking for community pages and neighbourhood desks,
    which is precisely where an uncorroborated claim starts.
    """
    from app.config import settings

    seeds: set[str] = set()
    for group in (settings.IG_SEED_USERNAMES, settings.FB_PAGE_IDS,
                  settings.TELEGRAM_CHANNELS, settings.REDDIT_SUBREDDITS):
        seeds.update(handle.casefold() for handle, _ in group)
    return frozenset(seeds)


def _is_established(p: Post) -> bool:
    return (bool(p.author_verified)
            or (p.author_followers or 0) >= ESTABLISHED_FOLLOWERS
            or (p.author_handle or "").casefold() in _seed_handles())


def _engagement(p: Post, key: str) -> float:
    return (p.engagement or {}).get(key, 0) or 0


def _propagation(p: Post) -> float:
    """People actively passing the post on or arguing with it. Shares count
    triple: sharing *is* the spreading. Views are deliberately absent — a view
    is the platform's decision, not a person's."""
    return (_engagement(p, "likes")
            + 3 * _engagement(p, "shares")
            + 2 * _engagement(p, "comments"))


def _priority_score(p: Post) -> tuple[float, float, float]:
    """0-100 triage priority, plus the propagation total and outrunning ratio.

    Weighted so the queue leads with the most alarming *unconfirmed claim*
    rather than the most-viewed post. Alarm dominates; rumour phrasing is the
    strongest single signal that a post is a rumour rather than a report;
    propagation counts where the adapter could read it; raw views are capped at
    a tenth of the score so a million-view reel cannot buy its way to the top.
    """
    alarm = min(1.0, (p.concern_score or 0) / 100)
    passed_on = _propagation(p)
    traction = min(1.0, math.log10(1 + passed_on) / 3)
    reach = min(1.0, math.log10(1 + _engagement(p, "views")) / 6)
    rumour = _INTENT_WEIGHT.get(p.intent or "", 0.0)

    if passed_on >= MIN_INTERACTIONS_FOR_RATE:
        rate = passed_on / max(p.author_followers or 0, 100)
        outrunning = min(1.0, rate / EXCEPTIONAL_RATE)
    else:
        outrunning = 0.0

    score = 100 * (0.40 * alarm + 0.25 * rumour
                   + 0.25 * traction + 0.10 * reach)
    return round(score, 1), passed_on, outrunning


def _corroborator_index(posts: list) -> dict[str, set[str]]:
    """For each post id, the set of *other* authors making a near-identical claim.

    Built from an inverted phrase index rather than by comparing every post to
    every other one. The pairwise version is O(n²) — on this window that is over
    a million Jaccard computations per request, which is why the scan had to be
    kept small, and a scan kept small is exactly what makes a "no one else has
    posted this" conclusion unreliable: the corroborating post is simply outside
    the sample.
    """
    shingles = {p.id: _shingles(p.text) for p in posts}
    index: dict[str, list[str]] = defaultdict(list)
    for p in posts:
        for g in shingles[p.id]:
            index[g].append(p.id)

    by_id = {p.id: p for p in posts}
    ceiling = max(2, int(len(posts) * _COMMON_SHINGLE_RATIO))
    neighbours: dict[str, set[str]] = defaultdict(set)
    checked: set[tuple[str, str]] = set()
    for holders in index.values():
        if len(holders) < 2 or len(holders) > ceiling:
            continue
        for pos, a in enumerate(holders):
            for b in holders[pos + 1:]:
                if by_id[a].author_handle == by_id[b].author_handle:
                    continue
                pair = (a, b)
                if pair in checked:
                    continue
                checked.add(pair)
                if _jaccard(shingles[a], shingles[b]) >= SIM_THRESHOLD:
                    neighbours[a].add(by_id[b].author_handle)
                    neighbours[b].add(by_id[a].author_handle)
    return neighbours


#: Computed windows, keyed by hours: (computed_at, payload). The scan costs a
#: multi-second read of every post's engagement and fact-check JSON, while the
#: dashboard panel polls every 45s and the review page pages through the same
#: result — recomputing it per request made paging to page 2 cost as much as
#: the first load. A stale-by-up-to-90s rumour list is the right trade: the
#: ingestion tick is slower than that anyway.
_CACHE: dict[int, tuple[float, dict]] = {}
_CACHE_TTL = 300.0
#: Windows the ingestion tick keeps warm — the two the UI actually opens with.
_PRIMED_WINDOWS = (24, 72)


def prime_cache() -> None:
    """Recompute the common windows ahead of anyone asking for them.

    Called from the ingestion tick (off the event loop). Errors are the
    caller's to swallow: a cold cache is slow, not broken.
    """
    for hours in _PRIMED_WINDOWS:
        _CACHE[hours] = (time.monotonic(), _compute(hours))


def _compute(hours: int) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    with session_scope() as s:
        posts = s.exec(
            # The dozen columns this actually reads, not all thirty-eight.
            # Fifteen hundred posts × the unread remainder — class probability
            # vectors, evidence reports, LLM verification blobs — is a lot of
            # payload to drag across the network to compute a triage score.
            select(Post.id, Post.platform, Post.author_handle, Post.author_name,
                   Post.author_followers, Post.author_verified, Post.text,
                   Post.translation, Post.sentiment_label, Post.concern_score,
                   Post.engagement, Post.fact_check, Post.url, Post.location,
                   Post.language, Post.intent, Post.hashtags, Post.created_at)
            .where(Post.created_at >= since)
            # Recency, not concern: corroboration has to be judged against the
            # window as it happened. Ordering by concern makes the scan a biased
            # sample of alarming posts, in which quiet corroborating coverage is
            # missing by construction.
            .order_by(Post.created_at.desc()).limit(MAX_SCAN)
        ).all()
    if not posts:
        return {"items": [], "scanned": 0, "platforms": [], "locations": [],
                "dropped": {}}

    corroborators = _corroborator_index(posts)
    # How much each account posted in this window — the broadcast-channel test.
    # Counted over the scan rather than the database so it means "in the window
    # being triaged", which is the same window every other judgement here uses.
    volume = Counter(p.author_handle for p in posts)
    dropped = {"established": 0, "not_a_claim": 0, "low_concern": 0,
               "corroborated": 0}

    items = []
    for p in posts:
        # An established channel reporting something is the corroboration this
        # queue is looking for the absence of, so it cannot also be the rumour.
        if _is_established(p) or volume[p.author_handle] > BROADCAST_POSTS_IN_WINDOW:
            dropped["established"] += 1
            continue
        # Nothing that does not assert something checkable. This gate is what
        # keeps reels, promos and praise out; without it the rest of the
        # pipeline happily ranks them.
        if _claim_check(p):
            dropped["not_a_claim"] += 1
            continue
        if (p.concern_score or 0) < CONCERN_FLOOR:
            dropped["low_concern"] += 1
            continue

        priority, passed_on, outrunning = _priority_score(p)

        fc = p.fact_check or {}
        news_ok = fc.get("verdict") == "corroborated"
        source_count = 1 + len(corroborators.get(p.id, ()))

        # emerging-unverified = a claim, single-source, no independent confirmation
        if source_count > 1 or news_ok:
            dropped["corroborated"] += 1
            continue

        reasons = [f"concern {round(p.concern_score)}/100 "
                   f"({p.sentiment_label} sentiment)"]
        if p.intent == "rumor":
            reasons.append("carries the phrasing rumours are built from "
                           "(forward-this / the-media-won't-show-you)")
        elif p.intent == "call_to_action":
            reasons.append("asks people to do something, not just to read")
        if passed_on:
            reasons.append(f"{int(passed_on):,} weighted interactions on an "
                           f"account with {p.author_followers:,} followers")
        if outrunning >= 0.6:
            reasons.append("engagement is outrunning the account's own audience")
        if fc.get("verdict") in ("uncorroborated", "partially corroborated"):
            reasons.append(f"cross-source check: {fc['verdict']} — no independent news coverage")
        else:
            reasons.append("only this account has posted this claim so far — no corroboration")

        items.append({
            "post_id": p.id,
            "platform": p.platform,
            "author_handle": p.author_handle,
            "author_name": p.author_name,
            "author_followers": p.author_followers,
            "author_verified": p.author_verified,
            "text": (p.translation or p.text)[:220],
            "sentiment_label": p.sentiment_label,
            "concern_score": p.concern_score,
            "priority_score": priority,
            "intent": p.intent or "",
            "source_count": source_count,
            "url": p.url,
            "location": p.location or "",
            "language": p.language or "",
            "fact_check_verdict": fc.get("verdict", ""),
            "reasons": reasons,
            "created_at": (p.created_at.isoformat() + "Z") if p.created_at else "",
        })

    items.sort(key=lambda x: -x["priority_score"])
    return {
        "items": items,
        "scanned": len(posts),
        "dropped": dropped,
        # Facet values come from the unfiltered result so the filter dropdowns
        # do not shrink to whatever is already selected.
        "platforms": sorted({i["platform"] for i in items if i["platform"]}),
        "locations": sorted({i["location"] for i in items if i["location"]}),
    }


def detect_emerging(hours: int = 24, *, limit: int = 40, offset: int = 0,
                    platform: str = "", location: str = "",
                    min_priority: float = 0.0, sentiment: str = "") -> dict:
    """Filter and page the window's flagged posts (see `_compute` for the scan)."""
    hit = _CACHE.get(hours)
    if hit and (time.monotonic() - hit[0]) < _CACHE_TTL:
        base = hit[1]
    else:
        base = _compute(hours)
        _CACHE[hours] = (time.monotonic(), base)

    items = base["items"]
    if platform:
        items = [i for i in items if i["platform"].lower() == platform.lower()]
    if location:
        items = [i for i in items if i["location"].lower() == location.lower()]
    if sentiment:
        items = [i for i in items if i["sentiment_label"] == sentiment]
    if min_priority:
        items = [i for i in items if i["priority_score"] >= min_priority]

    total = len(items)
    page = items[max(0, offset): max(0, offset) + max(1, limit)]
    return {
        "window_hours": hours,
        "count": len(page),
        "total": total,
        "items": page,
        "scanned": base["scanned"],
        "dropped": base.get("dropped", {}),
        "platforms": base["platforms"],
        "locations": base["locations"],
    }
