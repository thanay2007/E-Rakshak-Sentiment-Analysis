# -*- coding: utf-8 -*-
"""Simulated ingestion source — the zero-key default.

Produces a realistic, labeled, multilingual social-media stream:
  • ~60 organic accounts + 3 bot networks with telltale signals
    (young accounts, numeric handles, tiny follower counts)
  • theme mix skewed to everyday life like real traffic
  • coordinated amplification bursts: bot nets repost near-duplicates of a
    hostile post within a ±3 minute window (what the network-analysis module is
    built to catch)
  • every post carries its ground-truth SENTIMENT (true_label — positive,
    negative or neutral) so /api/stats can report live accuracy against what
    the models predicted, plus an English gloss for the analyst

The same generator backfills seed history, drives the live stream tick and
builds the train/test datasets (with different RNG seeds).
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from app.data.templates import (CITIES, GROUPS, LANG_NAMES, OFFICIALS, PLACES,
                                 TEMPLATES, THEME_TONE, TIMES)
from app.schemas import RawPost

PLATFORMS = ["X", "Facebook", "Instagram", "Reddit"]
PLATFORM_WEIGHTS = [0.40, 0.25, 0.20, 0.15]

# Subject-matter mix of the simulated stream, skewed to ordinary city life the
# way real municipal traffic is. These are THEMES, not predictions — the label
# a post ends up with is its sentiment, derived per template below.
THEME_WEIGHTS = {
    "everyday": 0.55,
    "hostile": 0.17,
    "rumor": 0.16,
    "mobilization": 0.12,
}
# Themes whose posts are hostile enough to attract engagement the way real
# outrage does.
_CHARGED_THEMES = ("hostile", "rumor", "mobilization")

FIRST = ["Raj", "Amit", "Priya", "Neha", "Vikram", "Sanjay", "Kavita", "Rahul", "Meera", "Arjun",
         "Pooja", "Deepak", "Anita", "Suresh", "Jignesh", "Hetal", "Chirag", "Falguni", "Parth", "Krupa", "Sivahari"]
LAST = ["Patel", "Shah", "Desai", "Mehta", "Joshi", "Trivedi", "Vyas", "Gandhi", "Modi", "Bhatt",
        "Solanki", "Parmar", "Chauhan", "Jadeja", "Rana", "Prakash"]

BOT_NET_PREFIXES = ["desh_sachai", "bharat_awaaz", "asli_news"]


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


class Simulator:
    def __init__(self, seed: int = 1337, cities: list[str] | None = None) -> None:
        self.rng = random.Random(seed)
        self.cities = list(cities or CITIES)  # dataset builds pass disjoint city subsets
        self.authors = self._make_authors()
        self.bot_nets = self._make_bot_nets()

    # ── account pools ─────────────────────────────────────────────────────
    def _make_authors(self) -> list[dict]:
        authors = []
        for i in range(60):
            name = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
            handle = name.lower().replace(" ", "_") + str(self.rng.randint(1, 999))
            authors.append({
                "handle": handle, "name": name,
                "followers": self.rng.randint(80, 60000),
                "verified": self.rng.random() < 0.06,
                "age_days": self.rng.randint(200, 4000),
                "bot": False,
            })
        return authors

    def _make_bot_nets(self) -> list[list[dict]]:
        nets = []
        for prefix in BOT_NET_PREFIXES:
            net = []
            for _ in range(self.rng.randint(6, 9)):
                n = self.rng.randint(1000, 9999)
                net.append({
                    "handle": f"{prefix}_{n}", "name": f"{prefix.replace('_', ' ').title()} {n}",
                    "followers": self.rng.randint(3, 90),
                    "verified": False,
                    "age_days": self.rng.randint(5, 60),
                    "bot": True,
                })
            nets.append(net)
        return nets

    # ── post construction ────────────────────────────────────────────────
    def _slots(self, lang: str) -> dict:
        city = self.rng.choice(self.cities)
        return {
            "city": city,
            "place": self.rng.choice(PLACES),
            "official": self.rng.choice(OFFICIALS),
            "group": self.rng.choice(GROUPS[lang]),
            "time": self.rng.choice(TIMES[lang]),
        }

    def _engagement(self, theme: str, amplified: bool) -> dict:
        r = self.rng
        if theme not in _CHARGED_THEMES:
            e = {"likes": r.randint(2, 500), "shares": r.randint(0, 40),
                 "comments": r.randint(0, 60), "views": r.randint(100, 20000)}
        else:
            e = {"likes": r.randint(15, 900), "shares": r.randint(30, 600),
                 "comments": r.randint(5, 250), "views": r.randint(800, 90000)}
        if amplified:
            e["shares"] = int(e["shares"] * r.uniform(1.5, 3.0))
            e["views"] = int(e["views"] * r.uniform(1.5, 2.5))
        return e

    def make_post(self, ts: datetime, theme: str | None = None,
                  author: dict | None = None, cluster_id: str = "",
                  text_override: str | None = None, template: dict | None = None) -> RawPost:
        r = self.rng
        if theme is None:
            theme = r.choices(list(THEME_WEIGHTS), weights=list(THEME_WEIGHTS.values()))[0]
        if template is None:
            template = r.choice(TEMPLATES[theme])
        lang = template["lang"]
        slots = self._slots(lang)
        text = text_override if text_override is not None else template["text"].format(**slots)
        gloss = template["gloss"].format(**slots)
        tags = [t.format(**slots).replace(" ", "") for t in template["tags"]]
        if r.random() < 0.4 and tags:
            text = text + " " + " ".join("#" + t for t in tags)

        author = author or r.choice(self.authors)
        platform = r.choices(PLATFORMS, weights=PLATFORM_WEIGHTS)[0]
        amplified = bool(cluster_id)
        pid = r.randint(10**14, 10**15 - 1)
        url_map = {
            "X": f"https://x.com/{author['handle']}/status/{pid}",
            "Facebook": f"https://facebook.com/{author['handle']}/posts/{pid}",
            "Instagram": f"https://instagram.com/p/{pid}",
            "Reddit": f"https://reddit.com/r/gujarat/comments/sim{pid}",
        }
        lat, lon = CITIES[slots["city"]]
        return RawPost(
            platform=platform,
            author_handle=author["handle"], author_name=author["name"],
            author_followers=author["followers"], author_verified=author["verified"],
            author_account_age_days=author["age_days"],
            text=text, translation=gloss,
            hashtags=tags,
            location=slots["city"],
            latitude=round(lat + r.uniform(-0.05, 0.05), 4),
            longitude=round(lon + r.uniform(-0.05, 0.05), 4),
            engagement=self._engagement(theme, amplified),
            url=url_map[platform],
            cluster_id=cluster_id, is_amplified=amplified,
            # ground truth is the SENTIMENT, which is the only thing the
            # models are asked to predict — the theme just picked the text
            true_label=template.get("tone") or THEME_TONE[theme] or "neutral",
            created_at=_utc(ts),
        )

    # ── coordinated amplification bursts ─────────────────────────────────
    def _mutate(self, text: str) -> str:
        r = self.rng
        suffixes = [" 👆👆", " Forward 🙏", " !!", " ⚠️", " #Viral", " share max", " 🔁", ""]
        t = text + r.choice(suffixes)
        if r.random() < 0.3:
            t = t.replace("!", "!!", 1)
        if r.random() < 0.2 and " " in t:
            words = t.split(" ")
            i = r.randrange(len(words))
            words[i] = words[i].upper() if words[i].isascii() else words[i]
            t = " ".join(words)
        return t

    def make_burst(self, ts: datetime) -> list[RawPost]:
        """One origin hostile post + near-duplicate reposts from a bot net
        inside a tight time window — the signature of coordinated amplification."""
        r = self.rng
        theme = r.choice(_CHARGED_THEMES)
        template = r.choice(TEMPLATES[theme])
        cluster_id = "burst-" + uuid.uuid4().hex[:8]
        # Burst window ENDS at ts so live bursts never emit future timestamps
        origin_ts = ts - timedelta(seconds=240)
        origin = self.make_post(origin_ts, theme=theme, cluster_id=cluster_id, template=template)
        posts = [origin]
        net = r.choice(self.bot_nets)
        for bot in r.sample(net, k=min(len(net), r.randint(4, 7))):
            dt = origin_ts + timedelta(seconds=r.randint(20, 200))
            posts.append(self.make_post(
                dt, theme=theme, author=bot, cluster_id=cluster_id,
                template=template, text_override=self._mutate(origin.text),
            ))
        return posts

    # ── seed history + live stream ───────────────────────────────────────
    def history(self, hours: int = 48, end: datetime | None = None) -> list[RawPost]:
        end = end or datetime.now(timezone.utc).replace(tzinfo=None)
        posts: list[RawPost] = []
        burst_hours = set(self.rng.sample(range(hours), k=max(3, hours // 12)))
        for h in range(hours, 0, -1):
            hour_start = end - timedelta(hours=h)
            # diurnal curve: quiet 1-6 IST-ish, busy evenings
            local_h = (hour_start.hour + 5) % 24  # rough IST offset
            base = 4 if local_h < 7 else (14 if 17 <= local_h <= 23 else 9)
            n = max(1, int(self.rng.gauss(base, 2)))
            for _ in range(n):
                ts = hour_start + timedelta(seconds=self.rng.randint(0, 3599))
                posts.append(self.make_post(ts))
            if (h - 1) in burst_hours:
                posts.extend(self.make_burst(hour_start + timedelta(minutes=self.rng.randint(5, 50))))
        posts.sort(key=lambda p: p.created_at)
        return posts

    def stream_tick(self) -> list[RawPost]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        r = self.rng
        posts = [self.make_post(now - timedelta(seconds=r.randint(0, 3)))
                 for _ in range(r.choices([1, 2, 3], weights=[0.55, 0.3, 0.15])[0])]
        if r.random() < 0.07:
            posts.extend(self.make_burst(now))
        return posts


_simulator: Simulator | None = None


def get_simulator() -> Simulator:
    global _simulator
    if _simulator is None:
        _simulator = Simulator()
    return _simulator
