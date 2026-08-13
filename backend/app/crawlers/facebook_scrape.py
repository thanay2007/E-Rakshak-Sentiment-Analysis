"""Facebook adapter via a real logged-in browser — no Meta app review.

Adapted from a donated Selenium + BeautifulSoup page scraper: same approach
(drive Chrome, scroll the page feed, parse the rendered HTML), rewritten to
emit RawPost against this project's seed-page strategy instead of writing a
JSON master file for a single news page.

Runs instead of the official FacebookCollector when no FB_ACCESS_TOKEN is set.
It reads the *same* FB_PAGE_IDS list, so dropping a Graph API token into .env
upgrades the source in place with no other config change — and no duplicate
ingestion, because the registry runs exactly one adapter per platform.

Unofficial, and it is worth being clear about what that means: this is a real
account browsing real pages, so Facebook can rate-limit it, checkpoint it, or
disable it. Use a dedicated burner account, never a personal one, and leave the
politeness gaps alone. FB_SCRAPE_MIN_INTERVAL_SECONDS defaults to 30 minutes
for that reason, not because reading is slow.

The browser runs in one persistent Chrome profile (FB_PROFILE_DIR). That is
load-bearing, not tidiness: Facebook binds a session to the `datr` device
cookie of the browser it was issued in, so a fresh profile each cycle presents
a known session on an unknown device and Facebook revokes it — characteristically
letting the first request through and refusing every one after. One durable
profile is one durable device.

Auth, in order of preference — every route is tried until one *verifies*
(a `c_user` cookie present and no login form on the page):
  1. the profile itself — a login done once via
     `python -m app.crawlers.facebook_login` lives here and needs no
     credentials in .env at all. This is the route that holds.
  2. FB_C_USER + FB_XS (+ FB_DATR) — cookies copied from a browser already
     logged into facebook.com (DevTools > Application > Cookies). Copy `datr`
     too: without the device cookie the session is being moved to a device
     Facebook has never seen, which is what gets it killed.
  3. backend/fb_cookies.json — a previously saved cookie jar, refreshed after
     every successful cycle (Facebook rotates these).
  4. FB_EMAIL / FB_PASSWORD form login — last resort. An automated login from a
     datacenter IP is what usually triggers the checkpoint.

There is no keyword search here, deliberately. Facebook's public search is
JS-gated, paginated behind opaque cursors and heavily rate-limited to logged-in
sessions — running it every cycle is the fastest way to lose the account.
`watch_terms` is therefore accepted and unused.

Coverage widens by adding pages instead. Two rosters feed the rotation and both
are read the same way: FB_PAGE_IDS, the official desks this deployment always
watches, and backend/discovered_accounts.json — the local news, food, college,
community and neighbourhood pages found by `python -m
app.crawlers.facebook_discover`, which runs Facebook's page search once, under
a human's eye, rather than inside the crawl loop. That is where a city's actual
sentiment is: the municipal corporation's page carries what the city announces,
and the community page two streets away carries what people think of it.

A discovered page that cannot be read three cycles running is dropped from the
roster. Discovery is deliberately cheap and therefore imprecise, and a page
that no longer loads costs a full page load every time its turn comes round.
Configured seeds are never dropped — those are a deliberate choice, and a
deployment is entitled to keep watching a page that is quiet this week.

What each post yields: message text (with "See more" expanded), the permalink,
post age, hashtags, attached fbcdn media, and a best-effort reaction/comment/
share count. Engagement is best-effort on purpose — Facebook renders those
counts through obfuscated class names that change without notice, so a missing
count reads as 0 rather than failing the post. The text and the permalink are
what the pipeline actually scores.

Selenium is fully synchronous, so the whole cycle runs in one worker thread via
asyncio.to_thread — a blocking browser call on the event loop would stall the
ingestion tick and the API with it. The driver is built and quit inside each
cycle: a Chrome kept alive for hours between 30-minute reads is a few hundred
MB of resident memory and a zombie process on every crash.
"""
import asyncio
import html as html_lib
import json
import logging
import random
import re
import time
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from app.config import BASE_DIR, settings
from app.crawlers import roster
from app.crawlers.base import Collector
from app.crawlers.common import extract_hashtags, rotate
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

COOKIES_FILE = BASE_DIR / "fb_cookies.json"
# How long the adapter stays offline after every auth route was refused.
# Repeated failed logins are themselves a risk signal to Facebook, so a dead
# credential must not be retried every tick — but the window is short enough
# that fixing .env or dropping in a new fb_cookies.json takes effect without a
# restart.
AUTH_RETRY_MINUTES = 30
PAGE_LOAD_TIMEOUT = 45
SCROLL_PAUSE = 3.0
MAX_MEDIA_PER_POST = 6
# Page name and follower count are chrome, not content: re-reading them every
# cycle is wasted parsing, and they barely move.
PROFILE_TTL_HOURS = 6
# Failed reads before a *discovered* page is dropped from the roster. Three
# rather than one because a single failure is usually the network or a slow
# render, and dropping a good page on that would quietly narrow coverage.
MAX_PAGE_STRIKES = 3

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# ---- parsing ---------------------------------------------------------------

_COUNT = r"(\d[\d.,]*\s*[KkMm]?)"
_COMMENTS_RE = re.compile(_COUNT + r"\s*comments?\b", re.I)
_SHARES_RE = re.compile(_COUNT + r"\s*shares?\b", re.I)
_VIEWS_RE = re.compile(_COUNT + r"\s*views?\b", re.I)
_REACTIONS_RE = re.compile(_COUNT + r"\s*(?:reactions?|people reacted|others?\b)", re.I)
_FOLLOWERS_RE = re.compile(_COUNT + r"\s*followers", re.I)
_BARE_COUNT_RE = re.compile(r"^\d[\d.,]*\s*[KkMm]?$")
# Engagement-bar action labels -> the metric the node's text is counting.
_ARIA_COUNT_METRICS = {
    "like": "likes", "react": "likes",
    "leave a comment": "comments", "comment": "comments",
    "share": "shares",
    "send this to friends or post it on your profile.": "shares",
}

# A post's permalink, in every shape Facebook currently serves one. `fbid=` is
# the logged-in feed's only usable one: there the timestamp link's href is
# nothing but tracking parameters, and the photo link is what carries an id.
_PERMALINK_RE = re.compile(
    r"(/posts/|/videos/|/reel/|/photos?/|permalink\.php|story_fbid=|fbid=|/share/[pv]/)")
_POST_ID_RE = re.compile(
    r"(?:story_fbid=|fbid=|/posts/|/videos/|/reel/|/share/[pv]/)([A-Za-z0-9]+)")
# The site root, which is what a tracking-only href cleans down to.
_ROOTS = ("https://www.facebook.com", "https://www.facebook.com/")

# "4h", "2 d", "35 mins" — the relative label Facebook puts on the permalink.
_REL_TIME_RE = re.compile(
    r"^\s*(\d+)\s*(m|mins?|minutes?|h|hrs?|hours?|d|days?|w|weeks?|y|yrs?|years?)\b",
    re.I)
_REL_UNITS = {"m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
              "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
              "d": 86400, "day": 86400, "days": 86400,
              "w": 604800, "week": 604800, "weeks": 604800,
              "y": 31536000, "yr": 31536000, "yrs": 31536000,
              "year": 31536000, "years": 31536000}
_ABS_TIME_FORMATS = (
    # Logged in, the timestamp link's aria-label is the exact posting time:
    # "Wednesday 12 August 2026 at 08:59". Worth preferring over the "15h" in
    # its text — that rounds, and rounding is what puts a post in the wrong
    # bucket on every trend chart.
    "%A %d %B %Y at %H:%M", "%A %d %B %Y at %I:%M %p",
    "%A %B %d, %Y at %H:%M", "%A %B %d, %Y at %I:%M %p",
    "%d %B %Y at %H:%M", "%B %d, %Y at %I:%M %p",
    "%B %d at %I:%M %p", "%d %B at %H:%M",
    "%B %d, %Y", "%d %B %Y", "%B %d")

_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December")
# "…12 August 2026 at 08:59" — a month name and a year, which no button label
# or engagement count has. Used to pick the timestamp out of the aria-labels.
_ABS_DATE_HINT_RE = re.compile(rf"(?:{_MONTHS})\b.*\b\d{{4}}", re.I)
_BARE_REL_TIME_RE = re.compile(r"^\d+\s*[hmdwy]$", re.I)
# One segment of the header line Facebook renders above a post body: a
# timestamp, an audience marker, or an edit flag, followed by its separator.
# Matched by *shape* rather than by "everything before the first ·" — the
# unanchored version deletes real content from any post using the character,
# and "Helpline · 100 · call it if the road floods" is exactly such a post.
# A text node with nothing in it but Facebook's own furniture. Matched whole,
# never as a prefix: "Public" here is the audience marker standing alone, while
# "Public toilets on Ring Road are locked" is a post about a grievance.
_CHROME_ONLY_RE = re.compile(
    r"(?:shared with public|shared with friends|public|friends|only me|"
    r"edited|sponsored|follow|following|see more|see less|see original|"
    r"see translation|just now|yesterday|active now|·|\s)*", re.I)
_CHROME_PREFIX_RE = re.compile(
    r"^\s*(?:\d+\s*(?:[hmdwy]|mins?|minutes?|hrs?|hours?|days?|weeks?|yrs?|years?)"
    r"|just now|yesterday(?:\s+at\s+[\d: ]*[ap]m)?"
    r"|shared with public|public|friends|edited|sponsored"
    rf"|(?:{_MONTHS})\s+\d{{1,2}}(?:,\s*\d{{4}})?(?:\s+at\s+[\d: ]*[ap]m)?"
    r"|\d{1,2}\s+(?:" + _MONTHS + r")(?:\s+\d{4})?)"
    r"\s*·\s*", re.I)

# Where the post message lives when Facebook still labels it. When it does not
# — which is most of the modern feed — _post_text falls back to the longest
# dir="auto" block in the article.
_MESSAGE_SELECTORS = ('[data-ad-preview="message"]',
                      '[data-ad-comet-preview="message"]',
                      '[data-testid="post_message"]',
                      ".userContent")

# What wraps one post. See _post_containers for why it takes two selectors.
_POST_CONTAINER_SELECTOR = 'div[role="article"], [aria-posinset]'
_COMMENT_LABEL_RE = re.compile(r"\s*(?:comment|reply)\s+by\b", re.I)

# Static UI assets and avatar thumbnails, which are not post media.
_MEDIA_SKIP = ("rsrc.php", "emoji.php", "spacer.gif", "blank.gif", "/static.",
               "_s32x32", "_p32x32", "_s50x50", "_p50x50", "c0.0.32.32")

# Expanders clicked before the post is read. Two different jobs:
#
#   "See more"     — the post is truncated, and without this it is scored on
#                    its first two lines.
#   "See original" — the post is being shown *machine-translated*. That button
#                    only exists when Facebook has already replaced the text,
#                    which happens whenever the account has "automatically
#                    translate" on, and the crawler's UI is pinned to English
#                    so every Gujarati and Hindi post is a candidate. Left
#                    unclicked, this deployment would score Facebook's English
#                    guess instead of what a Surat resident actually wrote:
#                    the sentiment model is fine-tuned on Gujarati, Hindi and
#                    romanized text, the language column would read "English"
#                    for the whole city, and the evidence quoted back to an
#                    officer would be a translation presented as the source.
#
# "See translation" is deliberately NOT here — clicking that would cause the
# very substitution the line above exists to undo.
_SEE_MORE_JS = """
let clicked = 0;
const wanted = ['see more', 'view more', '… see more',
                'see original', 'see original text'];
for (const el of document.querySelectorAll('div[role="button"],span[role="button"]')) {
  if (clicked >= 16) break;
  const t = (el.innerText || '').trim().toLowerCase();
  if (wanted.includes(t)) { try { el.click(); clicked++; } catch (e) {} }
}
return clicked;
"""


class AuthFailed(RuntimeError):
    """Every auth route was refused. Carries the per-route reasons, because
    "Facebook login failed" is not something an operator can act on and
    "fb_cookies.json: session expired (Facebook served the login page)" is."""


def _count(raw: str | None) -> int:
    """'1.2K' / '3,456' / '2M' -> int. 0 for anything unparseable — an absent
    count is not a signal, and guessing one would be."""
    if not raw:
        return 0
    text = raw.strip().replace(",", "").replace(" ", "")
    mult = 1
    if text[-1:].lower() == "k":
        mult, text = 1_000, text[:-1]
    elif text[-1:].lower() == "m":
        mult, text = 1_000_000, text[:-1]
    try:
        return int(float(text) * mult)
    except ValueError:
        return 0


def _first_count(pattern: re.Pattern, text: str) -> int:
    match = pattern.search(text)
    return _count(match.group(1)) if match else 0


def _post_time(label: str) -> datetime | None:
    """The permalink's timestamp label -> naive UTC, or None when it cannot be
    read. None is honest: ingestion timestamps the post at collection, which is
    right for a fresh feed item and clearly better than a fabricated date."""
    label = (label or "").strip()
    if not label:
        return None
    now = datetime.utcnow()
    low = label.lower()
    if low.startswith("just now") or low.startswith("now"):
        return now
    if low.startswith("yesterday"):
        return now - timedelta(days=1)
    if (rel := _REL_TIME_RE.match(label)):
        unit = _REL_UNITS.get(rel.group(2).lower())
        if unit:
            return now - timedelta(seconds=int(rel.group(1)) * unit)
    # "August 5 at 3:12 PM" and friends. Facebook drops the year for posts from
    # the current year, which strptime backfills as 1900 — hence the fix-up.
    cleaned = re.sub(r"\s+", " ", label.replace("·", " ")).strip()
    for fmt in _ABS_TIME_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if parsed.year == 1900:
            parsed = parsed.replace(year=now.year)
            if parsed > now + timedelta(days=1):  # December post read in January
                parsed = parsed.replace(year=now.year - 1)
        return parsed
    return None


def _absolute(href: str) -> str:
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        return f"https://www.facebook.com{href}"
    return href


def _clean_url(href: str) -> str:
    """Drop Facebook's per-impression tracking query (__cft__, __tn__, eav...),
    which makes the same post look like a new URL on every read, while keeping
    the parameters that actually identify it."""
    base, _, query = href.split("#")[0].partition("?")
    if not query:
        return _absolute(base)
    keep = [p for p in query.split("&")
            if p.split("=")[0] in ("story_fbid", "fbid", "id", "v", "set")]
    return _absolute(f"{base}?{'&'.join(keep)}" if keep else base)


def _clean_text(text: str) -> str:
    """Post body -> what a person actually wrote.

    Facebook's rendered article carries chrome inside the same text nodes: a
    relative timestamp and audience marker on the front, the reaction summary
    and the Like/Comment/Share bar on the back. Left in, all of it reaches the
    sentiment model as if the author had typed it.
    """
    if not text:
        return ""
    text = html_lib.unescape(text)
    # "4h · Shared with Public · ", "August 5 at 3:12 PM · Edited · " — one
    # recognised segment at a time, because there can be several.
    while (match := _CHROME_PREFIX_RE.match(text)):
        text = text[match.end():]
    # The same header with no separator left. The negative lookahead is what
    # keeps "2 days later the road reopened" intact — without it the "d" of
    # "days" reads as the day unit and the sentence loses its first two words.
    text = re.sub(r"^\s*\d+\s*[hmdwy](?![A-Za-z])\s*", "", text)
    # Trailing engagement bar. Cut at the summary line rather than stripping
    # the words, so a post that legitimately ends in "...please share" survives.
    text = re.sub(r"\s*All reactions:.*$", "", text, flags=re.I | re.S)
    text = re.sub(r"\s*(?:Like\s+Comment\s+Share|View \d+ more comments?)\b.*$",
                  "", text, flags=re.I | re.S)
    # The expander's own label ends up inside the message the moment we click
    # it — every expanded post otherwise ends "...પોલીસ. See less".
    text = re.sub(r"\s*See (?:more|less|translation|original)\s*$", "",
                  text, flags=re.I)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)  # control chars
    text = re.sub(r"[ \t]+", " ", text).strip()
    # A block that is *nothing but* chrome once the prefixes are off — the
    # header line "4h · Shared with Public" leaves "Shared with Public"
    # behind, because the audience marker is only recognised above when a
    # separator follows it and here it ends the line.
    #
    # That residue is not merely untidy, and the way it bites is
    # language-specific: _post_text keeps the *longest* block a post owns, so
    # eighteen characters of English chrome beats a short Gujarati or Hindi
    # sentence and becomes the post. The English posts that make up the test
    # corpus are long enough never to lose that comparison, which is exactly
    # why this survived — every affected post still looked like a post.
    return "" if _CHROME_ONLY_RE.fullmatch(text) else text


def _is_comment(node) -> bool:
    """Facebook labels a comment for screen readers — "Comment by D.C. Koli 15
    hours ago" — and that label is the only dependable way to tell one from a
    post. The structure is not: logged *out*, comments are role="article"
    nested inside the post's own role="article"; logged *in*, they are
    top-level role="article" siblings and the post is not an article at all.
    A parser that leans on the nesting is therefore correct in exactly one of
    the two sessions, and the logged-in one is the one that collects.
    """
    return bool(_COMMENT_LABEL_RE.match(node.get("aria-label") or ""))


def _post_containers(soup) -> list:
    """The feed's posts, comments excluded.

    Two selectors because Facebook uses two shapes. `[aria-posinset]` is the
    feed-item wrapper of a logged-in session, where the post body sits outside
    any article; `div[role="article"]` is the whole post logged out. Whichever
    is present, anything nested inside an already-accepted container is a part
    of that post rather than a post of its own.
    """
    accepted, accepted_ids = [], set()
    for node in soup.select(_POST_CONTAINER_SELECTOR):
        if _is_comment(node):
            continue
        if any(id(parent) in accepted_ids for parent in node.parents):
            continue
        accepted.append(node)
        accepted_ids.add(id(node))
    return accepted


def _owned_by(node, container) -> bool:
    """True when `node` belongs to the post itself rather than to a comment
    inside it. The thread under a municipal post is thirty strangers, and
    folding their words into the post's text scores them as the police force's
    own.

    A labelled comment always ends the walk. A nested role="article" only does
    so when the container is itself an article — that is the logged-out shape,
    where comments nest inside the post. Logged in, the *post body* is the
    nested article inside an [aria-posinset] wrapper, so treating that as a
    boundary makes a post disown its own timestamp and engagement bar.
    """
    container_is_article = container.get("role") == "article"
    for parent in node.parents:
        if parent is container:
            return True
        if _is_comment(parent):
            return False
        if container_is_article and parent.get("role") == "article":
            return False
    return False


def _owned(container, selector: str) -> list:
    return [n for n in container.select(selector) if _owned_by(n, container)]


def _post_text(container) -> str:
    for selector in _MESSAGE_SELECTORS:
        for element in _owned(container, selector):
            if (text := _clean_text(element.get_text("\n", strip=True))):
                return text
    # Obfuscated feed DOM: no labelled message container, so take the longest
    # dir="auto" block the post owns. Longest wins because the header, the
    # timestamp and the button labels are all short and the message is not.
    best = ""
    for element in _owned(container, 'div[dir="auto"]'):
        text = _clean_text(element.get_text("\n", strip=True))
        if len(text) > len(best):
            best = text
    return best


def _permalink(container) -> tuple[str, str]:
    """(url, post id) for the post, or ('', '') when neither can be read."""
    for anchor in _owned(container, "a[href]"):
        href = anchor["href"]
        if not _PERMALINK_RE.search(href):
            continue
        url = _clean_url(href)
        # Logged in, the timestamp's href is *only* tracking parameters, which
        # clean down to the site root — a link to everything is a link to
        # nothing, and taking it would give every post on the page one URL.
        if not url or url in _ROOTS:
            continue
        match = _POST_ID_RE.search(url)
        return url, (match.group(1) if match else url)
    return "", ""


def _timestamp_label(container) -> str:
    """When the post was published, in whatever form this DOM offers it.

    Facebook stopped emitting <abbr>/<time> years ago. What it does emit, for
    screen readers, is the exact date on the timestamp link's aria-label —
    preferred here over the "15h" in the link's own text, because the visible
    label rounds and the aria one does not.
    """
    for tag in _owned(container, "time"):
        if (stamp := tag.get("datetime")):
            return stamp
    for node in _owned(container, "[aria-label]"):
        label = node["aria-label"]
        if _ABS_DATE_HINT_RE.search(label):
            return label
    for anchor in _owned(container, "a[href]"):
        if _PERMALINK_RE.search(anchor["href"]):
            label = anchor.get_text(" ", strip=True)
            if label and len(label) < 40:
                return label
    # Last resort: the bare "15h" token on its own, which is all a post whose
    # timestamp link carries nothing but tracking parameters ever shows.
    for node in _owned(container, "span, div, a"):
        label = node.get_text(" ", strip=True)
        if _BARE_REL_TIME_RE.match(label):
            return label
    return ""


def _author(container) -> tuple[str, str]:
    """(display name, handle) of whoever wrote the post, ('', '') if unreadable.

    Worth the effort even though we navigate one page at a time: a page feed
    also carries what the page shared from elsewhere, and attributing a shared
    post to the page that reshared it misidentifies the source — which on this
    system feeds straight into the network graph.
    """
    for selector in ("h2 a[href]", "h3 a[href]", "h4 a[href]", "strong a[href]"):
        for anchor in _owned(container, selector):
            href = anchor["href"]
            if _PERMALINK_RE.search(href):  # the timestamp link, not the author
                continue
            name = anchor.get_text(" ", strip=True)
            if not name or len(name) > 80:
                continue
            path = _clean_url(href).split("facebook.com/")[-1]
            handle = path.split("?")[0].strip("/")
            if "profile.php" in path:
                handle = path.partition("id=")[2] or handle
            return name, handle
    return "", ""


def _media_urls(container) -> list[str]:
    urls: list[str] = []

    def add(url: str | None) -> None:
        if not url or len(urls) >= MAX_MEDIA_PER_POST:
            return
        if not url.startswith(("http://", "https://")) or url in urls:
            return
        if any(skip in url for skip in _MEDIA_SKIP):
            return
        if "fbcdn" in url or "scontent" in url or "cdninstagram" in url:
            urls.append(url)

    for img in _owned(container, "img"):
        alt = (img.get("alt") or "").lower()
        if any(word in alt for word in ("profile picture", "avatar", "emoji", "icon")):
            continue
        add(img.get("src"))
    for video in _owned(container, "video"):
        add(video.get("src"))
    return urls


def _labelled_counts(container) -> dict:
    """Counts from the logged-in engagement bar.

    There the number is not in the label at all: the bar renders a bare "23" on
    a node whose aria-label is the *action* ("Like", "Leave a comment"). So the
    label says which metric it is and the text says how much — neither alone is
    enough, and a regex looking for "23 reactions" finds nothing.
    """
    counts: dict[str, int] = {}
    for node in _owned(container, "[aria-label]"):
        metric = _ARIA_COUNT_METRICS.get(node["aria-label"].strip().lower())
        if not metric or metric in counts:
            continue
        value = node.get_text(" ", strip=True)
        if _BARE_COUNT_RE.match(value):
            counts[metric] = _count(value)
    return counts


def _engagement(container) -> dict:
    """Reaction / comment / share counts, best-effort across both DOM shapes.

    Everything here reads aria-labels, the only part of the engagement bar
    Facebook has to keep human-readable for screen readers and therefore the
    only part not obfuscated — first as action labels carrying a bare count,
    then as self-describing ones ("312 reactions", "See all 41 comments"),
    then the post's own text.
    """
    labelled = _labelled_counts(container)
    labels = " ".join(
        node["aria-label"] for node in _owned(container, "[aria-label]")
        if node.get("aria-label"))
    text = container.get_text(" ", strip=True)

    def pick(metric: str, pattern: re.Pattern) -> int:
        return (labelled.get(metric)
                or _first_count(pattern, labels)
                or _first_count(pattern, text))

    return {
        "likes": pick("likes", _REACTIONS_RE),
        "comments": pick("comments", _COMMENTS_RE),
        "shares": pick("shares", _SHARES_RE),
        "views": pick("views", _VIEWS_RE),
    }


def _page_url(page: str) -> str:
    """A numeric seed is a profile id, which has no vanity URL."""
    page = page.strip().strip("/")
    if page.startswith("http"):
        return page
    if page.isdigit():
        return f"https://www.facebook.com/profile.php?id={page}"
    return f"https://www.facebook.com/{page}"


class FacebookScrapeCollector(Collector):
    name = "Facebook (browser)"
    min_interval_seconds = settings.FB_SCRAPE_MIN_INTERVAL_SECONDS
    # Legitimately slow rather than stuck: a cycle is a browser launch plus a
    # page load and several scrolls for each seed page, and scrolling is what
    # makes Facebook render the posts at all. Budgeted per page so adding
    # seeds does not silently start truncating the cycle.
    timeout_seconds = 90 + 90 * max(1, settings.FB_PAGES_PER_CYCLE
                                    + settings.FB_SEED_PAGES_PER_CYCLE)

    def __init__(self) -> None:
        self._seen: set[str] = set()
        # page -> (read_at_monotonic, display name, followers)
        self._page_meta: dict[str, tuple[float, str, int]] = {}
        self._page_cursor = 0
        self._seed_cursor = 0
        # page -> consecutive cycles it could not be read (see _pages).
        self._strikes: dict[str, int] = {}
        # Why the last auth attempt failed, and when — see AUTH_RETRY_MINUTES.
        self._auth_error = ""
        self._auth_failed_at = 0.0

    def _has_credentials(self) -> bool:
        return bool((settings.FB_PROFILE_DIR / "Default").exists()
                    or (settings.FB_C_USER and settings.FB_XS)
                    or COOKIES_FILE.exists()
                    or (settings.FB_EMAIL and settings.FB_PASSWORD))

    def _pages(self) -> list[tuple[str, str]]:
        """Everything to read: the configured seeds, then whatever discovery
        found. Deduped on the handle, seeds first, so a page that is both keeps
        the city tag it was configured with."""
        return roster.merged("facebook", settings.FB_PAGE_IDS)

    def is_configured(self) -> bool:
        if not self._has_credentials() or not self._pages():
            return False
        if self._auth_error:
            if time.monotonic() - self._auth_failed_at < AUTH_RETRY_MINUTES * 60:
                return False
            # Window is up: clear the latch so the next tick tries again and
            # can report a *current* reason rather than a stale one.
            self._auth_error = ""
        return True

    def status_detail(self) -> str:
        if self._auth_error:
            return self._auth_error
        if self._has_credentials() and not self._pages():
            return ("Facebook credentials are set but there are no pages to "
                    "read. Run `python -m app.crawlers.facebook_discover` to "
                    "find the pages in each target city, or set seeds by hand, "
                    'e.g. FB_PAGE_IDS_RAW=["suratcitypolice:Surat"]')
        return ""

    # ---- browser ----------------------------------------------------------

    def _build_driver(self, page_load_strategy: str = "normal"):
        """A Chrome in the persistent profile.

        `page_load_strategy` is "eager" for the discovery command, and the
        reason is measured rather than theoretical: Facebook's search results
        page never fires the load event — a feed with a live connection never
        finishes loading — so a normal-strategy `driver.get` sits there until
        PAGE_LOAD_TIMEOUT expires, turning a 25-second search into 70. Eager
        returns at DOMContentLoaded, which loses nothing here because every
        caller waits for the JS-rendered content explicitly afterwards.
        """
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.page_load_strategy = page_load_strategy
        # One durable profile, so Facebook sees the same device every cycle.
        # Chrome locks the directory, so the login command cannot run while the
        # crawler is mid-cycle — that shows up as a clear "profile in use"
        # error rather than a silent auth failure.
        settings.FB_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={settings.FB_PROFILE_DIR}")
        options.add_argument("--profile-directory=Default")
        if settings.FB_SCRAPE_HEADLESS:
            options.add_argument("--headless=new")
        for arg in ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                    "--window-size=1440,2400", "--disable-extensions",
                    "--disable-notifications", "--disable-blink-features=AutomationControlled",
                    "--lang=en-US", f"--user-agent={UA}"):
            options.add_argument(arg)
        # English UI is not cosmetic: every selector and count regex below reads
        # Facebook's own labels, and a Gujarati or Hindi chrome breaks them.
        options.add_experimental_option("prefs", {"intl.accept_languages": "en-US,en"})
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        driver = webdriver.Chrome(options=options)  # Selenium Manager fetches the driver
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        # Explicit waits only. An implicit wait makes every find_elements() that
        # legitimately matches nothing — most of them, on a DOM this variable —
        # cost the full timeout.
        driver.implicitly_wait(0)
        return driver

    # ---- auth -------------------------------------------------------------

    def _logged_in(self, driver) -> bool:
        """`c_user` is the account id Facebook only sets for a live session; a
        login form on the page means it served the login wall instead."""
        from selenium.webdriver.common.by import By

        if not any(c["name"] == "c_user" for c in driver.get_cookies()):
            return False
        return not driver.find_elements(By.ID, "pass")

    def _apply_cookies(self, driver, cookies: list[dict]) -> None:
        # add_cookie only accepts cookies for the domain currently loaded, so
        # the (logged-out) shell has to be fetched first.
        driver.get("https://www.facebook.com/")
        for cookie in cookies:
            entry = {"name": cookie["name"], "value": cookie["value"],
                     "domain": cookie.get("domain", ".facebook.com"),
                     "path": cookie.get("path", "/")}
            if isinstance(cookie.get("expiry"), (int, float)):
                entry["expiry"] = int(cookie["expiry"])
            try:
                driver.add_cookie(entry)
            except Exception as exc:  # one malformed cookie must not kill the jar
                log.debug("facebook: skipped cookie %s: %s", cookie.get("name"), exc)
        driver.get("https://www.facebook.com/")

    def _password_login(self, driver) -> None:
        from selenium.webdriver.common.by import By

        driver.get("https://www.facebook.com/login")
        time.sleep(2)
        driver.find_element(By.ID, "email").send_keys(settings.FB_EMAIL)
        driver.find_element(By.ID, "pass").send_keys(settings.FB_PASSWORD)
        driver.find_element(By.NAME, "login").click()
        time.sleep(6)
        current = driver.current_url
        if "checkpoint" in current or "two_step" in current or "two_factor" in current:
            raise RuntimeError(
                "Facebook wants a checkpoint or 2FA code cleared — run "
                "`python -m app.crawlers.facebook_login` once, on a machine "
                "with a screen, and log in by hand")

    def _cookie_jar(self) -> list[dict]:
        jar = [{"name": "c_user", "value": settings.FB_C_USER},
               {"name": "xs", "value": settings.FB_XS}]
        if settings.FB_DATR:
            jar.append({"name": "datr", "value": settings.FB_DATR})
        return jar

    def _auth_routes(self) -> list[tuple[str, object]]:
        # The persistent profile comes first and needs no work: if a previous
        # login is still valid, Chrome has already sent its cookies and the
        # verification below is the whole check.
        routes: list[tuple[str, object]] = [
            ("profile", lambda d: d.get("https://www.facebook.com/"))]
        if settings.FB_C_USER and settings.FB_XS:
            routes.append(("FB_C_USER/FB_XS", lambda d: self._apply_cookies(
                d, self._cookie_jar())))
        if COOKIES_FILE.exists():
            routes.append((COOKIES_FILE.name, lambda d: self._apply_cookies(
                d, json.loads(COOKIES_FILE.read_text(encoding="utf-8")))))
        if settings.FB_EMAIL and settings.FB_PASSWORD:
            routes.append(("FB_EMAIL/FB_PASSWORD", self._password_login))
        return routes

    def _authenticate(self, driver) -> str:
        """The label of the route that worked, or AuthFailed with every reason."""
        if not self._has_credentials():
            raise AuthFailed(
                "no Facebook session — run `python -m app.crawlers.facebook_login` "
                "once, or set FB_C_USER/FB_XS (with FB_DATR) in backend/.env")
        routes = self._auth_routes()
        failures: list[str] = []
        for label, authenticate in routes:
            try:
                authenticate(driver)
            except Exception as exc:
                failures.append(f"{label}: {exc}")
                log.warning("facebook: %s refused — %s", label, exc)
                continue
            if self._logged_in(driver):
                log.info("facebook: authenticated via %s", label)
                return label
            failures.append(f"{label}: session rejected — Facebook served the "
                            "login page (the cookies are expired or revoked)")
        raise AuthFailed("; ".join(failures))

    def _save_cookies(self, driver) -> None:
        """Facebook rotates session cookies as it goes; persisting the current
        jar is what lets the next cycle skip the login step entirely."""
        try:
            COOKIES_FILE.write_text(json.dumps(driver.get_cookies(), indent=2),
                                    encoding="utf-8")
        except Exception as exc:  # a read-only volume must not kill a good cycle
            log.warning("facebook: could not save %s: %s", COOKIES_FILE.name, exc)

    # ---- scraping ---------------------------------------------------------

    def _meta(self, page: str, html: str) -> tuple[str, int]:
        """(display name, followers) for a page, cached for PROFILE_TTL_HOURS.

        Only a *successful* read is cached. The header renders after the first
        posts do, so an early parse legitimately finds no follower count — and
        caching that miss for six hours turns a two-second race into a page
        whose audience reads as zero for the rest of the day, which is the one
        number the amplification scoring leans on.
        """
        hit = self._page_meta.get(page)
        if hit and time.monotonic() - hit[0] < PROFILE_TTL_HOURS * 3600:
            return hit[1], hit[2]
        soup = BeautifulSoup(html, "html.parser")
        heading = soup.find("h1")
        name = heading.get_text(" ", strip=True) if heading else ""
        if not name and soup.title:
            name = soup.title.get_text(strip=True).split("|")[0].strip()
        name = name or page
        followers = _first_count(_FOLLOWERS_RE, soup.get_text(" ", strip=True))
        if followers:
            self._page_meta[page] = (time.monotonic(), name, followers)
        return name, followers

    def _resolve_meta(self, driver, page: str) -> tuple[str, int]:
        """_meta, given a couple of extra seconds for the header to arrive."""
        name, followers = page, 0
        for attempt in range(3):
            name, followers = self._meta(page, driver.page_source)
            if followers:
                break
            if attempt < 2:
                time.sleep(2)
        return name, followers

    def _articles_to_posts(self, html: str, page: str, city: str,
                           page_name: str, followers: int) -> list[RawPost]:
        posts: list[RawPost] = []
        for article in _post_containers(BeautifulSoup(html, "html.parser")):
            url, post_id = _permalink(article)
            text = _post_text(article)
            if not text:
                continue
            # A post with no readable permalink still counts — fall back to the
            # text so the seen-set can dedupe it across scrolls, which is where
            # Facebook re-renders the same article again and again.
            key = post_id or f"{page}:{hash(text[:200])}"
            if key in self._seen:
                continue
            self._seen.add(key)

            author_name, handle = _author(article)
            # Facebook serves the vanity URL in the page's own casing
            # ("SuratCityPolice") whatever casing the seed was configured in,
            # so this comparison has to be case-insensitive — otherwise the
            # page's own posts look like reshares and lose their reach.
            is_page = not handle or handle.casefold() == page.casefold()
            posts.append(RawPost(
                platform="Facebook",
                author_handle=handle or page,
                author_name=author_name or page_name,
                # Only the page's own follower count is known; a shared post's
                # original author is left at 0 rather than credited with the
                # resharing page's reach.
                author_followers=followers if is_page else 0,
                text=text[:1000],
                hashtags=extract_hashtags(text),
                location=city,
                engagement=_engagement(article),
                url=url,
                media_urls=_media_urls(article),
                created_at=_post_time(_timestamp_label(article)),
            ))
        return posts

    def _scrape_page(self, driver, page: str, city: str) -> list[RawPost]:
        driver.get(_page_url(page))
        time.sleep(SCROLL_PAUSE)
        page_name, followers = self._resolve_meta(driver, page)

        posts: list[RawPost] = []
        for scroll in range(max(1, settings.FB_SCRAPE_SCROLLS)):
            if scroll:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(SCROLL_PAUSE)
            # Truncated posts arrive as "...See more" and would be scored on
            # their first two lines. Every other scroll: the click costs a
            # re-render, and the expansions persist as we scroll past them.
            if scroll % 2 == 0:
                try:
                    driver.execute_script(_SEE_MORE_JS)
                    time.sleep(1)
                except Exception as exc:
                    log.debug("facebook: See-more expansion failed on %s: %s", page, exc)
            # Parsed every scroll, not once at the end: Facebook recycles feed
            # DOM nodes, so a post scrolled well past is gone from page_source.
            posts.extend(self._articles_to_posts(
                driver.page_source, page, city, page_name, followers))
            if len(posts) >= settings.FB_POSTS_PER_PAGE:
                break
        return posts[:settings.FB_POSTS_PER_PAGE]

    def _strike(self, page: str, configured: set[str]) -> None:
        """One failed read. A discovered page that fails MAX_PAGE_STRIKES
        cycles running is deleted, deleted-and-renamed, or restricted to
        followers — all of which cost a full page load every rotation and
        return nothing."""
        count = self._strikes.get(page, 0) + 1
        self._strikes[page] = count
        if count >= MAX_PAGE_STRIKES and page.casefold() not in configured:
            roster.prune("facebook", [page],
                         f"unreadable {count} cycles running")
            self._strikes.pop(page, None)

    def _cycle_pages(self) -> list[tuple[str, str]]:
        """This cycle's reading list: the configured seeds, then a slice of the
        discovered roster.

        Two budgets rather than one shared rotation. They are different kinds
        of page and want different rates: the seeds are the official desks an
        officer expects to be current, and there are a handful of them; the
        discoveries are hundreds of community and local-business pages where a
        sweep across the week is exactly right. Sharing one rotation makes the
        second silently starve the first — every page discovered pushes the
        police page further down a queue that already takes days to come round.
        """
        seeds = settings.FB_PAGE_IDS
        configured = {p.casefold() for p, _ in seeds}
        discovered = [(p, c) for p, c in self._pages()
                      if p.casefold() not in configured]

        if settings.FB_SEED_PAGES_PER_CYCLE > 0:
            seeds, self._seed_cursor = rotate(seeds, self._seed_cursor,
                                              settings.FB_SEED_PAGES_PER_CYCLE)
        else:  # 0: no separate seed budget, one rotation over everything
            seeds, discovered = [], self._pages()

        if settings.FB_PAGES_PER_CYCLE > 0:
            discovered, self._page_cursor = rotate(discovered, self._page_cursor,
                                                   settings.FB_PAGES_PER_CYCLE)
        return list(seeds) + list(discovered)

    def _collect_sync(self) -> list[RawPost]:
        configured = {p.casefold() for p, _ in settings.FB_PAGE_IDS}
        pages = self._cycle_pages()
        driver = self._build_driver()
        posts: list[RawPost] = []
        try:
            self._authenticate(driver)
            for index, (page, city) in enumerate(pages):
                if index:
                    # Jittered, because a page load every N seconds on the dot
                    # is a bot signature in a way a human's browsing is not.
                    time.sleep(random.uniform(4, 9))
                try:
                    found = self._scrape_page(driver, page, city)
                except Exception as exc:
                    log.warning("facebook: page %s failed: %s", page, exc)
                    self._strike(page, configured)
                    continue
                self._strikes.pop(page, None)
                log.info("facebook: %s -> %d posts", page, len(found))
                posts.extend(found)
            self._save_cookies(driver)
        finally:
            try:
                driver.quit()
            except Exception:  # a crashed browser has nothing left to close
                pass
        return posts

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        try:
            return await asyncio.to_thread(self._collect_sync)
        except AuthFailed as exc:
            # Latched, so the adapter reports offline and stops retrying for a
            # while. A credential Facebook has refused will not start working
            # because we asked again ninety seconds later, and repeated failed
            # logins are exactly the pattern that escalates a soft block.
            self._auth_error = str(exc)
            self._auth_failed_at = time.monotonic()
            log.warning("facebook: Facebook is OFFLINE — no auth route worked "
                        "(%s). Retrying in %d minutes.", exc, AUTH_RETRY_MINUTES)
            return []
        except Exception as exc:
            # Selenium is an optional dependency and Chrome is not a Python
            # package, so "it did not start" is a real deployment state and
            # deserves a reason an operator can act on rather than a traceback.
            reason = str(exc)
            if "cannot find chrome" in reason.lower() or "chromedriver" in reason.lower():
                reason = ("Chrome could not be started — install Google Chrome "
                          "on this host (Selenium fetches the driver itself)")
            elif isinstance(exc, ImportError):
                reason = "selenium is not installed — pip install -r requirements.txt"
            self._auth_error = reason
            self._auth_failed_at = time.monotonic()
            log.warning("facebook browser collect failed: %s", exc)
            return []
