# -*- coding: utf-8 -*-
"""Media-intelligence index: 'where else has this image appeared, and who posted it'.

We keep a fingerprint index of media SENTINEL has seen circulating across the
monitored seed sources. Each known image carries a 64-bit perceptual hash and
the list of accounts that posted it (its "appearances"). Reverse lookup hashes
the uploaded image and finds the nearest known item by Hamming distance.

Person finding + famous-personality filter:
  appearances are split into three buckets so an analyst isn't drowned by the
  hundreds of accounts a public figure's photo naturally appears on —
    • public_figures  — verified / official accounts of the real person
    • impersonators   — unverified accounts using the same name/photo (the risk)
    • other_accounts  — anonymous / bot-like re-posters (amplification)

For images not in the index (a genuinely new upload) we return the nearest
reference match with an honest confidence plus hand-off deep-links to public
reverse-image engines.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from app.osint.bot_score import score_account

# ── perceptual-hash utilities ──────────────────────────────────────────────

def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 64


def _confidence(distance: int) -> float:
    """64-bit hash: 0 bits = identical, ~>16 bits = unrelated."""
    return round(max(0.0, 1.0 - distance / 22.0), 3)


# ── seeded index of known circulating media ────────────────────────────────
# Hashes are stable, hand-picked 64-bit values so the demo is deterministic and
# the buckets below tell a realistic Gujarat-context story.

def _hash_from(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


_now = datetime.now(timezone.utc).replace(tzinfo=None)


def _appearance(platform, handle, name, followers, verified, age, hrs_ago,
                kind, url=""):
    return {
        "platform": platform, "handle": handle, "name": name,
        "followers": followers, "verified": verified,
        "account_age_days": age,
        "posted_at": (_now - timedelta(hours=hrs_ago)).isoformat() + "Z",
        "kind": kind,                       # public_figure | impersonator | reposter
        "url": url or f"https://{platform.lower()}.example/{handle}",
    }


_INDEX: list[dict] = [
    {
        "id": "img-riot-rumor",
        "hash": "e4c1a3b7d9f20518",
        "subject": "Old unrelated fire photo recycled as 'Surat riot' rumor",
        "first_seen_hours": 34,
        "context": "Fact-checked as a 2019 photo from another state, re-shared as a "
                   "current Surat law-and-order incident.",
        "appearances": [
            _appearance("X", "desh_sachai_4471", "Desh Sachai 4471", 42, False, 21, 33, "reposter"),
            _appearance("X", "bharat_awaaz_8820", "Bharat Awaaz 8820", 17, False, 9, 32, "reposter"),
            _appearance("Facebook", "asli_news_1290", "Asli News 1290", 63, False, 15, 31, "reposter"),
            _appearance("Instagram", "surat_alert_news", "Surat Alert News", 5100, False, 240, 30, "reposter"),
            _appearance("WhatsApp", "forwarded-broadcast", "Forwarded (many times)", 0, False, 0, 29, "reposter"),
        ],
    },
    {
        "id": "img-official-portrait",
        "hash": "1f2e3d4c5b6a7988",
        "subject": "District official portrait reused by fake handles",
        "first_seen_hours": 200,
        "context": "The real official's verified page plus several look-alike accounts "
                   "issuing statements in the official's name.",
        "appearances": [
            _appearance("X", "collector_surat", "Collector, Surat (Official)", 148000, True, 2100, 190, "public_figure"),
            _appearance("Facebook", "SuratCollectorOffice", "Surat Collectorate", 92000, True, 1800, 188, "public_figure"),
            _appearance("X", "collector_surat_real", "Collector Surat OFFICIAL✓", 900, False, 12, 20, "impersonator"),
            _appearance("Instagram", "surat.collector.updates", "Surat Collector Updates", 2300, False, 40, 14, "impersonator"),
            _appearance("Telegram", "collectorsurat_news", "Collector Surat News", 4100, False, 55, 10, "impersonator"),
        ],
    },
    {
        "id": "img-boycott-poster",
        "hash": "aa55cc33ee1188ff",
        "subject": "Boycott-campaign poster template",
        "first_seen_hours": 12,
        "context": "Identical poster pushed by a burst of young accounts sharing a "
                   "templated handle prefix — coordinated economic-exclusion campaign.",
        "appearances": [
            _appearance("X", "boycott_now_5501", "Boycott Now 5501", 8, False, 6, 11, "reposter"),
            _appearance("X", "boycott_now_5518", "Boycott Now 5518", 11, False, 6, 11, "reposter"),
            _appearance("X", "boycott_now_5533", "Boycott Now 5533", 5, False, 5, 10, "reposter"),
            _appearance("Instagram", "jaag_re_bharat", "Jaag Re Bharat", 15400, False, 95, 9, "reposter"),
        ],
    },
]


def scenario_for(seed: str, threat_label: str = "Neutral") -> dict | None:
    """Deterministically decide whether a corpus post 'carries' a known image and,
    if so, which one — so the feed-driven flow can resolve a post to its media
    without a downloadable original (the simulated stream has no real files).

    Returns the matching index item (with its perceptual hash) or None when the
    post has no attached media."""
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    prob_has_media = 0.6 if threat_label != "Neutral" else 0.22
    if (h % 1000) / 1000.0 >= prob_has_media:
        return None
    by_label = {
        "Fake News": "img-riot-rumor",
        "Inflammatory": "img-boycott-poster",
        "Incitement to Violence": "img-boycott-poster",
        "Neutral": "img-official-portrait",
    }
    pref = by_label.get(threat_label)
    pool = [it for it in _INDEX if it["id"] == pref] or _INDEX
    return pool[h % len(pool)]


def report_for_hash(phash: str, *, image_url: str = "") -> dict:
    """Bundle the reverse-image + people-finder views for a known hash."""
    return {"reverse_image": reverse_lookup(phash, image_url=image_url),
            "person": find_person(phash, image_url=image_url)}


def _bucketize(appearances: list[dict]) -> dict:
    public_figures, impersonators, others = [], [], []
    for a in appearances:
        enriched = dict(a)
        bot = score_account(
            a["handle"], name=a["name"], followers=a["followers"],
            account_age_days=a["account_age_days"], verified=a["verified"],
        )
        enriched["bot_score"] = bot["score"]
        enriched["bot_verdict"] = bot["verdict"]
        if a["kind"] == "public_figure" or a["verified"]:
            public_figures.append(enriched)
        elif a["kind"] == "impersonator":
            impersonators.append(enriched)
        else:
            others.append(enriched)
    return {
        "public_figures": public_figures,
        "impersonators": impersonators,
        "other_accounts": others,
    }


REVERSE_ENGINES = [
    ("Google Lens", "https://lens.google.com/uploadbyurl?url="),
    ("Yandex Images", "https://yandex.com/images/search?rpt=imageview&url="),
    ("Bing Visual Search", "https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:"),
    ("TinEye", "https://tineye.com/search?url="),
]


def _engine_links(image_url: str = "") -> list[dict]:
    return [{"name": n, "url": (base + image_url) if image_url else base.split("?")[0]}
            for n, base in REVERSE_ENGINES]


def reverse_lookup(phash: str | None, *, image_url: str = "", max_distance: int = 12) -> dict:
    """Find where an image (by perceptual hash) has appeared before."""
    if not phash:
        return {
            "matched": False,
            "reason": "No perceptual hash (non-image media).",
            "external_engines": _engine_links(image_url),
        }

    ranked = sorted(
        ({"item": it, "distance": hamming(phash, it["hash"])} for it in _INDEX),
        key=lambda r: r["distance"],
    )
    best = ranked[0]
    confident = best["distance"] <= max_distance
    item = best["item"]
    buckets = _bucketize(item["appearances"])
    platforms = sorted({a["platform"] for a in item["appearances"]})

    return {
        "matched": confident,
        "confidence": _confidence(best["distance"]),
        "hamming_distance": best["distance"],
        "query_hash": phash,
        "match": {
            "id": item["id"],
            "subject": item["subject"],
            "context": item["context"],
            "first_seen_hours_ago": item["first_seen_hours"],
            "total_appearances": len(item["appearances"]),
            "platforms": platforms,
            "platform_count": len(platforms),
            **buckets,
        } if confident else None,
        "nearest_reference": None if confident else {
            "subject": item["subject"], "hamming_distance": best["distance"],
        },
        "external_engines": _engine_links(image_url),
        "note": (
            "Matched against SENTINEL's monitored-media index."
            if confident else
            "No confident match in the monitored index — this appears to be new "
            "media. Continue the trace with the external reverse-image engines below."
        ),
    }


def find_person(phash: str | None, *, image_url: str = "") -> dict:
    """People-finder view of reverse_lookup: who is in the image and which of the
    matching accounts are the real (famous) person vs impersonators/re-posters."""
    rev = reverse_lookup(phash, image_url=image_url)
    if not rev.get("matched"):
        return {
            "identified": False,
            "reason": rev.get("note"),
            "external_engines": rev.get("external_engines", []),
        }
    m = rev["match"]
    famous = bool(m["public_figures"])
    return {
        "identified": True,
        "confidence": rev["confidence"],
        "subject": m["subject"],
        "is_public_figure": famous,
        "public_figures": m["public_figures"],
        "impersonators": m["impersonators"],
        "other_accounts": m["other_accounts"],
        "summary": (
            f"Photo linked to a public figure with {len(m['public_figures'])} official "
            f"account(s); flagged {len(m['impersonators'])} impersonator account(s) reusing "
            f"the same image."
            if famous else
            f"No verified owner found — image is being re-posted by "
            f"{len(m['other_accounts'])} account(s) across {m['platform_count']} platform(s)."
        ),
    }
