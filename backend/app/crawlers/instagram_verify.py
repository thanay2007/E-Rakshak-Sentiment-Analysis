# -*- coding: utf-8 -*-
"""Verify candidate Instagram seed handles before they go into config.

The seed list is not a wishlist. A handle that does not resolve costs a failed
private-API lookup every collection cycle and then contributes nothing, which
from the dashboard is indistinguishable from the city simply being quiet — the
exact failure that left Surat with no civic page for months while appearing
configured. A private account is the same problem with a different cause.

So every candidate is checked against the live API for four things:
  • it resolves at all
  • it is public (a private account returns no media to a non-follower)
  • it has posted recently — a dormant account re-serves its last posts forever,
    which would re-inject months-old content into the feed every cycle
  • it has an audience worth monitoring

Usage (from backend/):
    python -m app.crawlers.instagram_verify handle1 handle2 ...
    python -m app.crawlers.instagram_verify --candidates    # the built-in list

Print-only: it never edits config.py. Copy the PASS lines into
IG_SEED_USERNAMES_RAW yourself, so what is monitored stays a deliberate choice.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

# Civic/official candidates per target city, to be checked rather than trusted.
# Municipal corporations, city police and district administrations — the
# accounts whose comment threads carry actual municipal grievance.
CANDIDATES: dict[str, list[str]] = {
    "Surat": [
        "suratcitypolice", "suratmunicipalcorporation", "smc_surat",
        "suratmunicipal", "surat_city_police", "collector_surat",
    ],
    "Ahmedabad": [
        "amdavadamc", "ahmedabadcitypolice", "ahmedabad_city_police",
        "collectorahmedabad", "amcahmedabad",
    ],
    "Vadodara": [
        "vmcvadodara", "vadodaracitypolice", "vadodara_city_police",
        "collectorvadodara", "ourvadodara",
    ],
    "Rajkot": [
        "rajkotmunicipalcorporation", "rmcrajkot", "rajkotcitypolice",
        "rajkot_city_police", "collectorrajkot", "rajkotmuni",
    ],
    "": [  # statewide desks — no city tag, geo-tagged per post
        "gujaratpolice", "cmogujarat", "gujaratinfo",
    ],
}

MIN_FOLLOWERS = 1_000
MAX_DORMANT_DAYS = 120


def verify(handles: list[tuple[str, str]], pause: float = 3.0) -> list[dict]:
    """Check each (handle, city). Returns a result row per handle."""
    from app.crawlers.instagrapi_ig import InstagrapiCollector

    collector = InstagrapiCollector()
    client = collector._login_sync()
    now = datetime.now(timezone.utc)
    results: list[dict] = []

    for username, city in handles:
        row: dict = {"handle": username, "city": city, "ok": False, "why": ""}
        try:
            uid = client.user_id_from_username(username)
            info = client.user_info(uid)
            row.update({
                "followers": info.follower_count,
                "private": info.is_private,
                "verified": info.is_verified,
                "name": info.full_name,
            })
            if info.is_private:
                row["why"] = "private — returns no media to a non-follower"
            elif info.follower_count < MIN_FOLLOWERS:
                row["why"] = f"only {info.follower_count} followers"
            else:
                medias = client.user_medias(uid, amount=1)
                if not medias:
                    row["why"] = "no readable media"
                else:
                    last = medias[0].taken_at
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    age = (now - last).days
                    row["last_post_days"] = age
                    if age > MAX_DORMANT_DAYS:
                        row["why"] = f"dormant — last post {age} days ago"
                    else:
                        row["ok"] = True
                        row["why"] = f"{info.follower_count:,} followers, last post {age}d ago"
        except Exception as exc:
            row["why"] = f"{type(exc).__name__}: {str(exc)[:90]}"
        results.append(row)
        print(("  PASS  " if row["ok"] else "  fail  ")
              + f"{username:34} {city or '(statewide)':12} {row['why']}", flush=True)
        time.sleep(pause)  # politeness — this is the private API
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("handles", nargs="*", help="handles to check (city via handle:City)")
    ap.add_argument("--candidates", action="store_true",
                    help="check the built-in per-city candidate list")
    ap.add_argument("--pause", type=float, default=3.0)
    args = ap.parse_args()

    todo: list[tuple[str, str]] = []
    if args.candidates:
        for city, names in CANDIDATES.items():
            todo.extend((n, city) for n in names)
    for h in args.handles:
        name, _, city = h.partition(":")
        todo.append((name.lstrip("@"), city))
    if not todo:
        ap.error("give handles, or --candidates")

    print(f"Checking {len(todo)} handles against the live API "
          f"({args.pause}s apart)...\n")
    results = verify(todo, pause=args.pause)

    good = [r for r in results if r["ok"]]
    print(f"\n{len(good)}/{len(results)} usable. Add to IG_SEED_USERNAMES_RAW:\n")
    for r in good:
        suffix = f":{r['city']}" if r["city"] else ""
        print(f'        "{r["handle"]}{suffix}",'
              f'   # {r.get("name", "")} — {r.get("followers", 0):,}')
    if not good:
        print("  (none — do not add anything)")
        sys.exit(1)


if __name__ == "__main__":
    main()
