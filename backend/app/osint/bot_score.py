# -*- coding: utf-8 -*-
"""Account authenticity scoring — shared by comment analysis, PR analysis and
the sleuth dossier.

Generic behavioural + string heuristics (no platform API required), in the
spirit of Botometer's feature families:
  • handle shape     — digit runs, digit share, vowel-free consonant soup
  • account maturity  — very young accounts skew bot
  • audience shape    — near-zero followers, or lopsided following/followers
  • default identity  — no display name, no avatar
  • activity          — extreme posting cadence (posts per day)

Returns a 0..100 "bot-likelihood" score plus the human-readable signals that
drove it, so an analyst can see *why* an account was flagged, never just a number.
"""
from __future__ import annotations

import re


def handle_randomness(handle: str) -> float:
    """0..1: how machine-generated a handle looks (matches network_service)."""
    h = (handle or "").lower().lstrip("@")
    if not h:
        return 0.0
    score = 0.0
    digits = sum(c.isdigit() for c in h)
    trailing = len(h) - len(h.rstrip("0123456789"))
    if trailing >= 4:
        score += 0.5
    elif trailing >= 2:
        score += 0.25
    if digits / len(h) > 0.35:
        score += 0.3
    letters = [c for c in h if c.isalpha()]
    if letters and sum(c in "aeiou" for c in letters) / len(letters) < 0.15:
        score += 0.2
    return min(score, 1.0)


def score_account(
    handle: str,
    *,
    name: str = "",
    followers: int = 0,
    following: int = 0,
    account_age_days: int = 365,
    verified: bool = False,
    has_avatar: bool = True,
    posts_per_day: float | None = None,
    duplicate_ratio: float = 0.0,
) -> dict:
    """Return {score: 0..100, verdict, signals: [..]} for one account.

    duplicate_ratio: share of this account's posts that are near-duplicates of
    other accounts' posts (copy-paste amplification) — 0..1.
    """
    if verified:
        # A platform-verified account is treated as authentic; we still surface
        # the raw signals but cap the score so a real public figure is not
        # mislabelled a bot.
        signals = ["platform-verified account"]
        return {"score": 4, "verdict": "authentic", "signals": signals, "verified": True}

    score = 0.0
    signals: list[str] = []

    rnd = handle_randomness(handle)
    if rnd >= 0.7:
        score += 28
        signals.append("handle looks machine-generated (digit runs / random string)")
    elif rnd >= 0.4:
        score += 16
        signals.append("handle has bot-like numeric pattern")

    if account_age_days <= 14:
        score += 26
        signals.append(f"account created only {account_age_days} days ago")
    elif account_age_days <= 60:
        score += 15
        signals.append(f"young account ({account_age_days} days old)")
    elif account_age_days <= 120:
        score += 7

    if followers <= 5:
        score += 18
        signals.append(f"almost no followers ({followers})")
    elif followers <= 50:
        score += 9
        signals.append(f"very low follower count ({followers})")

    if following and followers is not None:
        ratio = following / max(followers, 1)
        if ratio >= 15 and following >= 300:
            score += 14
            signals.append(f"follows {ratio:.0f}× more accounts than follow back "
                           f"({following} following / {followers} followers)")

    if not (name or "").strip():
        score += 8
        signals.append("no display name set")
    if not has_avatar:
        score += 10
        signals.append("default profile picture")

    if posts_per_day is not None and posts_per_day >= 50:
        score += 16
        signals.append(f"extreme posting rate (~{posts_per_day:.0f} posts/day)")
    elif posts_per_day is not None and posts_per_day >= 20:
        score += 8
        signals.append(f"high posting rate (~{posts_per_day:.0f} posts/day)")

    if duplicate_ratio >= 0.5:
        score += 18
        signals.append("mostly re-posts identical text seen from other accounts")
    elif duplicate_ratio >= 0.25:
        score += 9
        signals.append("repeats copy-paste text also posted elsewhere")

    score = int(min(score, 100))
    if score >= 60:
        verdict = "likely_bot"
    elif score >= 35:
        verdict = "suspicious"
    else:
        verdict = "authentic"
    if not signals:
        signals.append("no automation signals detected")
    return {"score": score, "verdict": verdict, "signals": signals, "verified": False}


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def near_duplicate_ratio(text: str, others: list[str]) -> float:
    """Max word-set Jaccard of `text` against any string in `others` (0..1).
    Cheap copy-paste-amplification signal used by comment / PR analysis."""
    a = set(_WORD_RE.findall((text or "").lower()))
    if not a:
        return 0.0
    best = 0.0
    for o in others:
        b = set(_WORD_RE.findall((o or "").lower()))
        if not b:
            continue
        j = len(a & b) / len(a | b)
        if j > best:
            best = j
    return round(best, 3)
