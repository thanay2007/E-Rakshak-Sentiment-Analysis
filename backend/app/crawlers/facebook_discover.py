# -*- coding: utf-8 -*-
"""Find the Facebook pages worth monitoring in each target city.

The seed list (FB_PAGE_IDS) is a handful of official desks, and monitoring only
those means monitoring what a city says about itself. Public sentiment lives on
everything else: the local news pages, the food and photography pages, the
college and community pages, the traders' associations, the neighbourhood
"updates" desks that carry a power cut before any official account does.

Nobody can maintain that list by hand across four cities, and guessing page
slugs is how this project ended up with a documented Surat seed that had never
existed. So this asks Facebook instead — its own page search, once, offline —
and keeps what it finds in backend/discovered_accounts.json, which the crawler
rotates over alongside the configured seeds.

Usage (from backend/):
    python -m app.crawlers.facebook_discover                  # every target city
    python -m app.crawlers.facebook_discover --city Surat
    python -m app.crawlers.facebook_discover --dry-run        # print, write nothing
    python -m app.crawlers.facebook_discover --min-followers 2000

Why this is a command and not a crawl leg: Facebook's search is the most
aggressively rate-limited surface it has, and running it inside the ingest loop
is the fastest way to lose the account — which is exactly why facebook_scrape
has no keyword search. A discovery run is a few dozen searches once a month,
under a human's eye, and the crawl loop stays a browser reading pages.

The result cards carry everything needed to judge a page without opening it:
name, category, street address, follower count and description all render in
the search results. That matters — visiting a hundred candidate pages to check
them would itself be the traffic pattern this file exists to avoid.

Location filtering is not optional. "Surat" matches Surat Thani in Thailand and
Surat in Bangladesh, both of which the search returns above real Gujarat pages,
and a roster polluted with them spends the crawl budget abroad.
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.config import settings
from app.crawlers import roster
from app.crawlers.facebook_scrape import (
    _FOLLOWERS_RE,
    AuthFailed,
    FacebookScrapeCollector,
    _first_count,
)

# What to search for, per city. The list is deliberately not "news and police":
# those are already seeds. Everything here is a category of page that carries
# how a city *feels* — where people complain, celebrate, organise and gossip.
CATEGORY_TERMS: list[str] = [
    "",                      # the bare city name — the biggest pages of all
    "news", "updates", "live",
    "police", "municipal corporation", "traffic",
    "food", "restaurant", "cafe",
    "blogger", "influencer", "photography", "diaries",
    "college", "students", "jobs",
    "business", "market", "real estate",
    "events", "hospital", "ngo",
    "fitness", "fashion", "youth", "community",
    # Romanized Gujarati/Hindi — what a Hinglish or Gujlish page calls itself.
    # These are not decoration: a page named "Surat Samachar" or "Rajkot
    # Khabar" posts in romanized script and is invisible to an English query
    # for "news", which is exactly the audience this deployment must not miss.
    "samachar", "khabar", "batmi", "gujarati news",
]

# The city name as residents write it, in every script the four cities are
# actually written in. This is the whole reach of the run: a page whose name
# is "સુરત સમાચાર" does not contain the string "Surat" anywhere, and no amount
# of English querying will ever return it.
CITY_ALIASES: dict[str, list[str]] = {
    "Surat": ["સુરત", "सूरत"],
    "Ahmedabad": ["અમદાવાદ", "अहमदाबाद", "Amdavad"],
    "Vadodara": ["વડોદરા", "वडोदरा", "Baroda"],
    "Rajkot": ["રાજકોટ", "राजकोट"],
}

# What an alias is searched for, in the alias's own script — a Gujarati city
# name with an English category term finds far less than one with "સમાચાર".
# Deliberately short per script: an alias exists to reach the pages an English
# query misses, and running all thirty categories against every alias would
# treble the length of a run to find the same pages twice.
ALIAS_TERMS_GUJARATI: list[str] = ["", "સમાચાર", "ન્યૂઝ", "ખબર"]
ALIAS_TERMS_HINDI: list[str] = ["", "समाचार", "न्यूज़", "खबर"]
ALIAS_TERMS_LATIN: list[str] = ["", "news", "samachar", "updates", "food"]

# Statewide desks, searched once with no city tag — they cover all four cities,
# so per-post geo-tagging beats a blanket label.
STATEWIDE_TERMS: list[str] = [
    "Gujarat news", "Gujarat samachar", "Gujarat police",
    "Gujarat government", "ગુજરાત સમાચાર", "गुजरात समाचार",
]


def _alias_terms(alias: str) -> list[str]:
    """The term list written in the same script as the alias."""
    if any("઀" <= ch <= "૿" for ch in alias):      # Gujarati block
        return ALIAS_TERMS_GUJARATI
    if any("ऀ" <= ch <= "ॿ" for ch in alias):      # Devanagari block
        return ALIAS_TERMS_HINDI
    return ALIAS_TERMS_LATIN

# Same-name places elsewhere in the world, which Facebook ranks above the real
# ones for a bare city query.
_FOREIGN_MARKERS = ("thailand", "surat thani", "suratthani", "bangladesh",
                    "pakistan", "indonesia", "sylhet", "nepal", "malaysia")

# Facebook's own URLs, which are not pages anybody wants to monitor.
_NOT_A_PAGE = {
    "settings", "groups", "pages", "marketplace", "watch", "events", "gaming",
    "help", "policies", "privacy", "legal", "login", "search", "bookmarks",
    "friends", "notifications", "messages", "reels", "stories", "photo",
    "profile.php", "people", "business", "ads", "home.php", "allactivity",
}

_PAGE_HREF_RE = re.compile(
    r"^https://www\.facebook\.com/(?:profile\.php\?id=(\d+)|([A-Za-z0-9._-]{3,60}))/?(?:\?|$)")
# Cards render a distance ("2.5 km"), an opening time and a Follow button
# around the useful text; none of them is a category.
_NOISE_SEGMENT_RE = re.compile(
    r"^(follow|message|like|liked|following|always open|open now|closed now|"
    r"permanently closed|\d[\d.,]*\s*(km|mi|m)|·|)$", re.I)
_COUNT_ANYWHERE_RE = re.compile(r"\d[\d.,]*\s*[KkMm]?\s*(followers|likes|people)", re.I)
# Pins, bullets, byte-order marks and whitespace that lead a card segment.
# Digits are deliberately NOT stripped: taking them off "1.3K followers"
# leaves "K followers", which no longer looks like a count and sails through
# as the page's category.
_LEADING_FURNITURE_RE = re.compile(r"^[^\w]+", re.UNICODE)


def _slug(href: str) -> str:
    """The page's stable identifier — its vanity name, or its numeric id when
    it has none. '' for anything that is not a page."""
    match = _PAGE_HREF_RE.match(href.split("&")[0].replace("&amp;", "&"))
    if not match:
        return ""
    slug = match.group(1) or match.group(2) or ""
    return "" if slug.casefold() in _NOT_A_PAGE else slug


def _segments(card) -> list[str]:
    raw = card.get_text("|", strip=True).split("|")
    return [s.strip() for s in raw if s.strip()]


def _category(segments: list[str]) -> str:
    """Facebook's own label for the page ("Media/news company"), when shown.

    Cards lead segments with a pin emoji, a bullet or a stray BOM, and the
    follower count is one of them — so a match anchored at the start of the
    string lets "📍 1K followers" through as the page's category. Leading
    furniture is stripped first and counts are rejected wherever they appear.
    """
    for segment in segments[1:5]:
        segment = _LEADING_FURNITURE_RE.sub("", segment).strip()
        if (segment and len(segment) < 44 and "," not in segment
                and not _COUNT_ANYWHERE_RE.search(segment)
                and not _NOISE_SEGMENT_RE.match(segment)):
            return segment
    return ""


def _city_of(text: str, cities: list[str]) -> str | None:
    """Which target city this page belongs to, or None to reject it.

    Two signals, and both are needed. The city name alone matches places on
    other continents; "Gujarat" alone matches a statewide page that belongs
    under no city tag. A page naming a city *and* sitting in Gujarat is the
    one this deployment wants.
    """
    low = text.casefold()
    if any(marker in low for marker in _FOREIGN_MARKERS):
        return None
    in_gujarat = "gujarat" in low or "ગુજરાત" in text
    for city in cities:
        names = [city] + CITY_ALIASES.get(city, [])
        if not any(name.casefold() in low for name in names):
            continue
        # A Gujarati-script or explicitly-Indian page needs no second signal —
        # "અમદાવાદ" is not a place in Thailand.
        if in_gujarat or "india" in low or any(
                name in text for name in CITY_ALIASES.get(city, [])):
            return city
        return None
    return None


def _parse_results(html: str, cities: list[str], min_followers: int,
                   query: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}
    for card in soup.select('div[role="article"]'):
        anchor = next((a for a in card.select("a[href]") if _slug(a["href"])), None)
        if anchor is None:
            continue
        slug = _slug(anchor["href"])
        text = card.get_text(" ", strip=True)
        city = _city_of(text, cities)
        if city is None:
            continue
        followers = _first_count(_FOLLOWERS_RE, text)
        if followers < min_followers:
            continue
        segments = _segments(card)
        name = anchor.get_text(" ", strip=True) or (segments[0] if segments else slug)
        found[slug.casefold()] = {
            "handle": slug,
            "city": city,
            "name": name[:120],
            "followers": followers,
            "category": _category(segments),
            "source": f"fb-search:{query}",
        }
    return list(found.values())


def _search(driver, query: str, scrolls: int) -> str:
    """One search, returned as the rendered HTML of the results only.

    Two things here are about time rather than correctness, and together they
    are the difference between a one-hour run and a four-hour one:

    * The page is never waited on. Facebook's search is a live feed that does
      not finish loading — even DOMContentLoaded is tens of seconds out — so
      the driver is told not to wait at all and the first result card is what
      signals readiness instead.
    * Only the result cards are pulled back, not `driver.page_source`. A
      scrolled search page is several megabytes, all of it serialised over the
      WebDriver protocol; the cards are a small fraction of that and are the
      only part parsed.
    """
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get(f"https://www.facebook.com/search/pages/?q={quote_plus(query)}")
    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="article"]')))
    except TimeoutException:
        # No cards at all: a query with genuinely no page results looks exactly
        # like this, so it is not an error — the caller reads it as 0 in scope.
        return ""
    for _ in range(max(0, scrolls)):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2.0)
    return driver.execute_script(
        "return Array.from(document.querySelectorAll('div[role=\"article\"]'))"
        ".map(n => n.outerHTML).join('');")


def _queries(cities: list[str], terms: list[str], statewide: bool) -> list[str]:
    out: list[str] = []
    for city in cities:
        out.extend(f"{city} {term}".strip() for term in terms)
        for alias in CITY_ALIASES.get(city, []):
            out.extend(f"{alias} {term}".strip() for term in _alias_terms(alias))
    if statewide:
        out.extend(STATEWIDE_TERMS)
    # Deduped, order kept: "Amdavad" plus the bare-name term collides with
    # nothing today, but a term list edited later should not silently double
    # the length of a run.
    seen, unique = set(), []
    for query in out:
        if query.casefold() not in seen:
            seen.add(query.casefold())
            unique.append(query)
    return unique


def discover(cities: list[str], terms: list[str], *, min_followers: int,
             scrolls: int, statewide: bool = True, write: bool = True) -> list[dict]:
    """Run the searches and return the pages worth monitoring.

    Everything here is one browser session doing what a person does. The gap
    between searches is jittered for the same reason facebook_scrape jitters
    between pages: a request every N seconds on the dot is a bot signature in a
    way a human's browsing is not.

    Each query's findings are written as they arrive rather than at the end. A
    full run is an hour of browsing, and an hour is long enough that something
    interrupts it — a checkpoint, a laptop lid, a dropped connection — so a run
    that only saved on success would routinely throw away everything it had
    found. The roster dedupes, so a re-run resumes rather than duplicates.
    """
    collector = FacebookScrapeCollector()
    driver = collector._build_driver(page_load_strategy="none")
    results: dict[str, dict] = {}
    queries = _queries(cities, terms, statewide)
    try:
        label = collector._authenticate(driver)
        print(f"authenticated via {label}\n", flush=True)
        for index, query in enumerate(queries, 1):
            if index > 1:
                time.sleep(random.uniform(5, 11))
            started = time.monotonic()
            try:
                html = _search(driver, query, scrolls)
            except Exception as exc:
                print(f"  [{index}/{len(queries)}] {query!r} failed: {exc}", flush=True)
                continue
            rows = _parse_results(html, cities, min_followers, query)
            fresh = [r for r in rows if r["handle"].casefold() not in results]
            for row in fresh:
                results[row["handle"].casefold()] = row
            if write and fresh:
                roster.add("facebook", fresh)
            print(f"  [{index}/{len(queries)}] {query:38} "
                  f"{len(rows):3} in scope, {len(fresh):3} new "
                  f"({len(results)} so far, {time.monotonic() - started:.0f}s)",
                  flush=True)
    finally:
        try:
            driver.quit()
        except Exception:  # a crashed browser has nothing left to close
            pass
    return sorted(results.values(), key=lambda r: -r["followers"])


def main() -> None:
    # Page names are Gujarati as often as not, and a Windows console defaults
    # to cp1252 — which does not merely mangle them, it raises, killing an
    # hour-long run at the moment it prints its results.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # a redirected stream may not support it
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--city", action="append", dest="cities",
                    help="limit to one city (repeatable); default TARGET_CITIES")
    ap.add_argument("--min-followers", type=int,
                    default=settings.FB_DISCOVER_MIN_FOLLOWERS)
    ap.add_argument("--scrolls", type=int, default=settings.FB_DISCOVER_SCROLLS,
                    help="result pages to load per query (~10 results each)")
    ap.add_argument("--terms", nargs="*", default=None,
                    help="override the category terms")
    ap.add_argument("--no-statewide", action="store_true",
                    help="skip the untagged Gujarat-wide searches")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what was found and write nothing")
    args = ap.parse_args()

    cities = args.cities or list(settings.TARGET_CITIES)
    terms = args.terms if args.terms is not None else CATEGORY_TERMS
    queries = len(_queries(cities, terms, not args.no_statewide))
    print(f"Searching Facebook for pages in {', '.join(cities)} — "
          f"{queries} queries, roughly {queries * 25 / 60:.0f} min\n", flush=True)

    try:
        found = discover(cities, terms, min_followers=args.min_followers,
                         scrolls=args.scrolls, statewide=not args.no_statewide,
                         write=not args.dry_run)
    except AuthFailed as exc:
        print(f"\nFacebook refused every login route ({exc}).\n"
              "Run `python -m app.crawlers.facebook_login` once, on a machine "
              "with a screen, and log in by hand.", file=sys.stderr)
        sys.exit(1)

    print(f"\n{len(found)} page(s) in scope:\n")
    for row in found:
        print(f"  {row['followers']:>9,}  {row['city']:<10} {row['handle']:<34} "
              f"{row['name'][:40]:<40} {row['category']}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return
    # Already written query by query; this is the belt-and-braces pass that
    # also reports the roster's true size, which is what an operator wants to
    # know after a run that may have resumed an earlier one.
    roster.add("facebook", found)
    print(f"\n{len(roster.entries('facebook'))} page(s) now in "
          f"{roster.ROSTER_FILE.name}. The crawler picks them up on its next "
          f"cycle — no restart needed.")


if __name__ == "__main__":
    main()
