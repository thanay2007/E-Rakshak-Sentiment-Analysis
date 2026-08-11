# -*- coding: utf-8 -*-
"""Comment-thread analysis: sentiment of the audience + bot-account detection.

Two entry points:
  • analyze_post_comments(post_id) — pulls the post from the DB and analyzes its
    comment thread. Real platforms return comments from the Graph/API layer; in
    the zero-key build we synthesize a realistic, deterministic thread (seeded by
    the post id) so the analysis surface is fully exercised.
  • analyze_comments(comments)     — analyze an arbitrary pasted list of comments
    ({author, text, followers?, account_age_days?}).

Every comment gets a sentiment (lite lexicon engine, no transformer needed) and a
bot-likelihood score. The thread-level verdict flags coordinated / botted comment
sections — the "checking bot accounts too" requirement.
"""
from __future__ import annotations

import random
from collections import Counter

from sqlmodel import select

from app.database import session_scope
from app.models import Post
from app.ml.sentiment import analyze_sentiment
from app.osint.bot_score import near_duplicate_ratio, score_account

# ── synthetic comment pools (deterministic per post) ────────────────────────
_ORGANIC = [
    ("Totally agree, this is a serious issue for our city.", "positive"),
    ("Where did this happen exactly? Need more details.", "neutral"),
    ("This looks fake, I saw the same photo last year.", "negative"),
    ("Police should verify before this spreads.", "neutral"),
    ("બહુ ખરાબ પરિસ્થિતિ છે, સાવધાન રહો.", "negative"),
    ("Aisा kuch nahi hua, ye afwah hai.", "negative"),
    ("Thanks for the update, staying safe.", "positive"),
    ("Can someone confirm this from an official source?", "neutral"),
    ("આ સાચું છે? મને શંકા છે.", "neutral"),
    ("Good work by the administration handling this.", "positive"),
    ("Log bina soche share kar rahe hain.", "negative"),
    ("Rajkot me bhi aisा dekha tha, careful rahna.", "neutral"),
]
_BOT_SPAM = [
    "Forward this to everyone 👆👆 #Viral share max 🔁",
    "SABKO BATAO!! Government hide kar rahi hai 🙏 forward",
    "Share max share max, truth must come out!!!",
    "Everyone must know this ⚠️ forward to 10 groups 👆",
    "Wake up people!! #FinalWarning share before deleted",
]
_BOT_PREFIXES = ["desh_sachai", "bharat_awaaz", "asli_news", "jaag_re", "sach_bolo"]
_FIRST = ["Raj", "Priya", "Amit", "Neha", "Vikram", "Kavita", "Jignesh", "Hetal", "Parth", "Krupa"]
_LAST = ["Patel", "Shah", "Desai", "Mehta", "Joshi", "Trivedi", "Solanki", "Jadeja"]


def _synth_thread(post: Post) -> list[dict]:
    rng = random.Random(int(post.id[:8], 16) if post.id[:8].isalnum() else hash(post.id))
    n_comments = min(max((post.engagement or {}).get("comments", 12), 6), 40)
    # threat/amplified posts attract a botted, hostile comment section
    hostile = post.sentiment_label == "negative" or post.is_amplified
    bot_share = 0.45 if hostile else 0.12
    out = []
    for i in range(n_comments):
        if rng.random() < bot_share:
            prefix = rng.choice(_BOT_PREFIXES)
            handle = f"{prefix}_{rng.randint(1000, 9999)}"
            out.append({
                "author_handle": handle,
                "author_name": f"{prefix.replace('_', ' ').title()} {rng.randint(10, 99)}",
                "text": rng.choice(_BOT_SPAM),
                "followers": rng.randint(2, 60),
                "account_age_days": rng.randint(4, 55),
                "verified": False,
            })
        else:
            name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
            text, _ = rng.choice(_ORGANIC)
            out.append({
                "author_handle": name.lower().replace(" ", "_") + str(rng.randint(1, 900)),
                "author_name": name,
                "text": text,
                "followers": rng.randint(80, 40000),
                "account_age_days": rng.randint(200, 3500),
                "verified": rng.random() < 0.05,
            })
    return out


def _analyze(comments: list[dict]) -> dict:
    texts = [c.get("text", "") for c in comments]
    analyzed = []
    for i, c in enumerate(comments):
        text = c.get("text", "")
        s_label, s_score = analyze_sentiment(text)
        others = texts[:i] + texts[i + 1:]
        dup = near_duplicate_ratio(text, others)
        bot = score_account(
            c.get("author_handle", ""), name=c.get("author_name", ""),
            followers=int(c.get("followers", 0) or 0),
            account_age_days=int(c.get("account_age_days", 365) or 365),
            verified=bool(c.get("verified", False)),
            duplicate_ratio=dup,
        )
        analyzed.append({
            "author_handle": c.get("author_handle", ""),
            "author_name": c.get("author_name", ""),
            "text": text,
            "sentiment_label": s_label,
            "sentiment_score": s_score,
            "duplicate_ratio": dup,
            "bot_score": bot["score"],
            "bot_verdict": bot["verdict"],
            "bot_signals": bot["signals"],
        })

    total = len(analyzed) or 1
    sent = Counter(a["sentiment_label"] for a in analyzed)
    bots = [a for a in analyzed if a["bot_verdict"] == "likely_bot"]
    suspicious = [a for a in analyzed if a["bot_verdict"] == "suspicious"]
    suspected = bots + suspicious           # anything above 'authentic'
    dup_heavy = sum(a["duplicate_ratio"] >= 0.6 for a in analyzed)
    bot_pct = round(100 * len(bots) / total, 1)
    suspected_pct = round(100 * len(suspected) / total, 1)

    # coordination: many near-duplicate comments from young, low-follower accounts
    coordinated = dup_heavy >= 3 and len(suspected) >= 3
    assessment = []
    if coordinated:
        assessment.append("Comment section shows coordinated activity — clusters of "
                          "near-identical comments from young, low-follower accounts.")
    if bot_pct >= 30:
        assessment.append(f"{bot_pct}% of commenters are likely bots — engagement is "
                          f"being artificially inflated.")
    elif suspected_pct >= 40:
        assessment.append(f"{suspected_pct}% of commenters show automation signals "
                          f"(young accounts, copy-paste text) — engagement looks inflated.")
    neg_pct = round(100 * sent["negative"] / total, 1)
    if neg_pct >= 50:
        assessment.append(f"Audience sentiment is predominantly negative ({neg_pct}%).")
    if not assessment:
        assessment.append("Comment section looks organic — no strong automation or "
                          "coordination signals.")

    analyzed.sort(key=lambda a: a["bot_score"], reverse=True)
    return {
        "total_comments": total,
        "sentiment_breakdown": {
            "positive": sent["positive"], "neutral": sent["neutral"],
            "negative": sent["negative"],
            "positive_pct": round(100 * sent["positive"] / total, 1),
            "neutral_pct": round(100 * sent["neutral"] / total, 1),
            "negative_pct": neg_pct,
        },
        "bot_analysis": {
            "likely_bots": len(bots),
            "suspicious": len(suspicious),
            "suspected_pct": suspected_pct,
            "bot_pct": bot_pct,
            "coordinated": coordinated,
        },
        "assessment": assessment,
        "comments": analyzed,
    }


def analyze_comments(comments: list[dict]) -> dict:
    return {"source": "provided", **_analyze(comments)}


def analyze_post_comments(post_id: str) -> dict:
    with session_scope() as s:
        post = s.get(Post, post_id)
        if not post:
            # allow analyzing the most recent threat post as a convenience
            post = s.exec(select(Post).order_by(Post.concern_score.desc()).limit(1)).first()
        if not post:
            return {"error": "No posts available to analyze."}
        ctx = {
            "post_id": post.id, "platform": post.platform,
            "author_handle": post.author_handle,
            "text": post.translation or post.text,
            "sentiment_label": post.sentiment_label,
            "engagement": post.engagement or {},
        }
        thread = _synth_thread(post)
    return {"source": "post", "post": ctx, "synthetic": True, **_analyze(thread)}
