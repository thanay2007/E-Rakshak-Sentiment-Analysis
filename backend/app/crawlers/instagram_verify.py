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

# Candidates per target city, to be checked rather than trusted.
#
# Deliberately much wider than the civic-page core it started as. Restricting
# the roster to municipal corporations and police meant monitoring only what
# the city *announces about itself* — press releases, and the grievance threads
# under them. Public sentiment in a city is not confined to seven accounts, so
# the roster now spans the categories that actually carry it:
#
#   • municipal corporation, and its ward/department desks
#   • city police, traffic police, and the district collectorate
#   • fire, RTO, civil hospital and other services people complain to
#   • local news outlets and their city-specific desks
#   • large citizen/community/civic pages
#
# Every one is a *candidate*. None of them belongs in config.py until it has
# passed the four checks below, which is the entire point of this file — a
# roster assembled by guessing handles is how Surat ended up with a documented
# seed page that had never existed.
CANDIDATES: dict[str, list[str]] = {
    "Surat": [
        # civic / official
        "suratcitypolice", "suratmunicipalcorporation", "smc_surat",
        "suratmunicipal", "surat_city_police", "collector_surat",
        "suratpolice", "surattrafficpolice", "surat_traffic_police",
        "suratdistrict", "suratcollector", "suratfirebrigade", "suratrto",
        # news / community
        "suratnews", "suratcity", "mysurat", "suratupdates", "surat_diamond_city",
        "voiceofsurat", "suratlive", "suratmirror", "suratdiaries",
        "suratplus", "wearesurat", "surat_gujarat",
    ],
    "Ahmedabad": [
        # civic / official
        "amdavadamc", "ahmedabadcitypolice", "ahmedabad_city_police",
        "collectorahmedabad", "amcahmedabad", "ahmedabadpolice",
        "ahmedabadtrafficpolice", "ahmedabad_traffic_police",
        "ahmedabaddistrict", "ahmedabadfirebrigade", "amtsahmedabad",
        "ahmedabadrto",
        # news / community
        "ahmedabadmirror", "ahmedabadnews", "myahmedabad", "amdavadi",
        "ahmedabadupdates", "ahmedabad_diaries", "ahmedabadcity",
        "amdavad", "wearahmedabad", "ahmedabadlive", "ahmedabadtimes",
    ],
    "Vadodara": [
        # civic / official
        "vmcvadodara", "vadodaracitypolice", "vadodara_city_police",
        "collectorvadodara", "vadodarapolice", "vadodaratrafficpolice",
        "vadodaradistrict", "vadodarafirebrigade", "vadodararto",
        # news / community
        "ourvadodara", "vadodaranews", "myvadodara", "vadodaraupdates",
        "barodacity", "barodadiaries", "vadodaramirror", "vadodaralive",
        "vadodaracity", "wearevadodara", "barodanews",
    ],
    "Rajkot": [
        # civic / official — Rajkot is the gap this roster most needs to close;
        # every previously checked handle is retried here alongside new ones.
        "rajkotmunicipalcorporation", "rmcrajkot", "rajkotcitypolice",
        "rajkot_city_police", "collectorrajkot", "rajkotmuni",
        "rajkotpolice", "rajkottrafficpolice", "rajkot_traffic_police",
        "rajkotdistrict", "rajkotfirebrigade", "rajkotrto",
        # news / community
        "rajkotnews", "myrajkot", "rajkotupdates", "rajkotcity",
        "rajkotdiaries", "rajkotlive", "rajkotmirror", "werajkot",
        "saurashtranews", "rajkot_gujarat",
    ],
    "": [  # statewide desks — no city tag, geo-tagged per post
        "gujaratpolice", "cmogujarat", "gujaratinfo", "gujarat_police",
        "infogujarat", "gujaratsamachar", "sandeshnews", "divyabhaskar",
        "vtvgujarati", "abpasmita", "tv9gujarati", "news18gujarat",
        "zee24kalak", "gstvnews", "gujarattourism",
    ],
}

MIN_FOLLOWERS = 1_000
MAX_DORMANT_DAYS = 120

#: Substrings of exceptions that mean "Instagram would not answer", as opposed
#: to "Instagram answered, and the account is no good". Keeping the two apart
#: matters more than it looks: a throttled lookup printed as `fail` reads
#: exactly like a handle that does not exist, and the whole point of this file
#: is to decide which handles are real. Recording a rate limit as a rejection
#: would retire a perfectly good civic page on the strength of a network blip.
_TRANSIENT = ("retryerror", "max retries", "timeout", "timed out", "connection",
              "temporarily", "please wait", "rate limit", "429", "502", "503")


def _is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT)


def _check_one(client, username: str, city: str, now) -> dict:
    """One handle, one verdict. Raises on transient failure so the caller can
    back off and retry; returns a row for any answer Instagram actually gave."""
    row: dict = {"handle": username, "city": city, "ok": False, "why": ""}
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
    return row


def verify(handles: list[tuple[str, str]], pause: float = 15.0,
           attempts: int = 3) -> list[dict]:
    """Check each (handle, city). Returns a result row per handle.

    Slow on purpose. Every handle costs two private-API calls, and checking a
    hundred of them back to back is precisely the burst that gets the account
    throttled — at which point the run stops measuring the handles and starts
    measuring the rate limiter. A transient failure is retried with a widening
    backoff rather than recorded, and anything still unanswered after
    `attempts` is reported as UNKNOWN, never as a rejection.
    """
    from app.crawlers.instagrapi_ig import InstagrapiCollector

    collector = InstagrapiCollector()
    client = collector._login_sync()
    now = datetime.now(timezone.utc)
    results: list[dict] = []

    for username, city in handles:
        row: dict | None = None
        for attempt in range(1, attempts + 1):
            try:
                row = _check_one(client, username, city, now)
                break
            except Exception as exc:
                if _is_transient(exc) and attempt < attempts:
                    backoff = pause * (2 ** attempt)
                    print(f"  ....  {username:34} throttled, retrying in {backoff:.0f}s "
                          f"({attempt}/{attempts - 1})", flush=True)
                    time.sleep(backoff)
                    continue
                row = {
                    "handle": username, "city": city, "ok": False,
                    "unknown": _is_transient(exc),
                    "why": f"{type(exc).__name__}: {str(exc)[:90]}",
                }
                break

        assert row is not None
        results.append(row)
        status = "  PASS  " if row["ok"] else ("  ????  " if row.get("unknown") else "  fail  ")
        print(status + f"{username:34} {city or '(statewide)':12} {row['why']}", flush=True)
        time.sleep(pause)  # politeness — this is the private API
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("handles", nargs="*", help="handles to check (city via handle:City)")
    ap.add_argument("--candidates", action="store_true",
                    help="check the built-in per-city candidate list")
    ap.add_argument("--pause", type=float, default=15.0,
                    help="seconds between handles (default 15 — a burst gets "
                         "the account throttled and the run stops meaning "
                         "anything)")
    ap.add_argument("--attempts", type=int, default=3,
                    help="tries per handle before reporting UNKNOWN")
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
          f"({args.pause}s apart, ~{len(todo) * args.pause / 60:.0f} min)...\n")
    results = verify(todo, pause=args.pause, attempts=args.attempts)

    good = [r for r in results if r["ok"]]
    unknown = [r for r in results if r.get("unknown")]
    print(f"\n{len(good)}/{len(results)} usable. Add to IG_SEED_USERNAMES_RAW:\n")
    for r in good:
        suffix = f":{r['city']}" if r["city"] else ""
        print(f'        "{r["handle"]}{suffix}",'
              f'   # {r.get("name", "")} — {r.get("followers", 0):,}')
    if not good:
        print("  (none — do not add anything)")
    if unknown:
        # Listed separately and loudly: these were never actually judged, so
        # re-running them later is the difference between "checked, no good"
        # and "not checked".
        print(f"\n{len(unknown)} handle(s) never got an answer — re-run these, "
              f"they are NOT rejections:")
        for r in unknown:
            suffix = f":{r['city']}" if r["city"] else ""
            print(f'    {r["handle"]}{suffix}')
    if not good:
        sys.exit(1)


if __name__ == "__main__":
    main()
