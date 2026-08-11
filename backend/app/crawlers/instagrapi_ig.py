"""Instagram adapter via instagrapi (github.com/subzeroid/instagrapi) — no Meta
app review, uses a real Instagram account session (use a burner, not a personal
account). Unofficial: it drives Instagram's private mobile API, so it can break
when Instagram changes it and the account can be rate-limited, challenged or
banned — keep volumes low and leave the politeness gaps alone.

Runs instead of the official InstagramCollector when no IG_ACCESS_TOKEN /
IG_BUSINESS_ACCOUNT_ID pair is set. It reads the *same* IG_SEED_USERNAMES list,
so dropping a Graph API token into .env upgrades the source in place with no
other config change.

Four things are fetched, and each answers a different question:

  * **posts** — media from the seed civic pages (what the city is announcing)
  * **hashtags** — media matching watchlist tags (what the city is saying)
  * **users** — media from accounts an officer put on the watchlist, plus the
    real profile behind an author discovered through a hashtag
  * **comments** — the thread under the loudest media of the cycle

Per media that yields: caption, hashtags (Unicode-aware, so Gujarati and
Devanagari tags survive), author handle + numeric user id, follower count,
verified flag, like/comment/play counts, every image or video in a carousel,
the geotag's real coordinates, and — the part the Graph API will never give you
— the actual comment threads.

Comments are emitted as posts in their own right, the same convention the
YouTube adapter uses. That is deliberate: on a municipal page the caption is a
press release and the grievance is thirty comments down, so a pipeline that
only scored captions would be reading the wrong half of the page.

The user leg exists because two facts are worth real money downstream and
neither arrives on its own. A watched handle was previously monitored only by
accident — when it happened to post something matching a keyword — and a media
found through a hashtag carries a UserShort, which has no follower count at
all, so every viral stranger was ingested as an account with zero reach and
scored accordingly.

Auth, in order of preference — and every one of them is tried, in order, until
one *verifies*:
  1. IG_SESSIONID — the `sessionid` cookie from a browser logged into
     instagram.com (DevTools > Application > Cookies). Cheapest and least
     likely to trip a login challenge, since no fresh login happens.
  2. backend/ig_session.json — a previously saved instagrapi device/session
     dump. Reused automatically once written; `python -m
     app.crawlers.instagrapi_login` is the supported way to create it, because
     it can answer the checkpoint challenge that the headless loop cannot.
  3. IG_USERNAME / IG_PASSWORD login (last resort — a login from a datacenter
     IP is what usually triggers the checkpoint challenge). On success the
     session is dumped to ig_session.json so later runs take route 2.

Walking all three rather than picking one matters more than it looks. A
`sessionid` is the shortest-lived credential here — Instagram revokes it on a
password change, a "log out of all devices", or its own risk signals — and an
expired one used to end the whole attempt, because the routes were an if/elif
chain on which credential was *present* rather than which one *worked*. A
stale cookie in .env therefore disabled Instagram outright while a perfectly
good username and password sat two lines below it.

Each route also gets a *fresh* client. A dead cookie leaves `authorization_data`
populated on the client that failed, and reusing that client for the password
route sends the dead credential along with the login.

And each route is verified with one private-API call before it is accepted,
because instagrapi's own verification cannot be trusted for this:
`login_by_sessionid` installs the cookie and then confirms it against the
*public* web GraphQL endpoint, which answers a revoked cookie with a redirect
loop to the login page. What surfaces is `TooManyRedirects` — a network-shaped
error that says nothing about auth — while the private API's honest
`login_required` / "You've Been Logged Out" is never seen.

When no route verifies, the adapter reports itself *offline* rather than
staying quietly configured. A platform that holds credentials it cannot use is
not a live source, and showing it as one is how this sat at zero posts behind a
green light for weeks: every leg returned [] on schedule and nothing in the
console disagreed.

instagrapi is fully synchronous (blocking `requests`), so every call here goes
through asyncio.to_thread — a blocking call on the event loop would stall the
whole ingestion tick and the API with it.
"""
import asyncio
import logging
import re
import time
from datetime import datetime
from typing import NamedTuple

from app.config import BASE_DIR, settings
from app.crawlers.base import Collector
from app.schemas import RawPost
from app.services.watch_targets import watched_accounts

log = logging.getLogger("sentinel.crawlers")

SESSION_FILE = BASE_DIR / "ig_session.json"
HASHTAG_MEDIA_LIMIT = 15
SEED_MEDIA_LIMIT = 12
# Watched accounts get a shallower read than the seed pages: there can be many
# of them, they are added ad hoc, and the recent few posts are what an officer
# who just added the handle actually wants to see.
WATCHED_MEDIA_LIMIT = 8
# A handle that does not resolve is usually a typo, a deleted account or a
# pattern the officer meant for another platform. Retrying it every cycle is a
# wasted private-API call each time, so failures are remembered this long.
MISSING_ACCOUNT_RETRY_HOURS = 6
# How long the adapter stays offline after every auth route was refused.
# Repeated failed logins are themselves a risk signal to Instagram, so a dead
# credential must not be retried every tick — but the window is short enough
# that fixing .env or dropping in a new ig_session.json takes effect without a
# restart.
AUTH_RETRY_MINUTES = 30

# Instagram usernames: letters, digits, dots, underscores, 30 max. The
# watchlist has no platform column, so its account rows are a mixed bag —
# Telegram channels, X handles, and patterns like "desh_sachai_*" that are
# meant as a wildcard. Anything that cannot be an IG handle is dropped here
# rather than spent as a failed lookup.
_IG_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")

# Hashtag body = word characters, and \w alone is not enough. It is Unicode-
# aware, but only for letters and digits (categories L*/N*) — combining marks
# are excluded, and every Indic vowel sign, anusvara and virama is one. Plain
# r"#(\w+)" therefore truncates #आंदोलन to "आ" at the anusvara, which on a
# Gujarat deployment silently guts most local-script tags while looking fine in
# English. These ranges add the marks back for Devanagari and Gujarati, plus
# ZWJ/ZWNJ, which sit *inside* correctly spelled Indic words.
_MARKS = (r"̀-ͯ"              # generic combining diacriticals
          r"ऀ-ःऺ-ॏ॑-ॗॢ-ॣ"  # Devanagari
          r"ઁ-ઃ઼-્ૢ-ૣ"              # Gujarati
          r"‌‍")              # ZWNJ / ZWJ
# Stops at the punctuation in "#surat,#protest" and "#rajkot." — the whitespace
# split this replaced returned the first as one unusable token and kept the
# trailing dot on the second.
_HASHTAG_RE = re.compile(rf"#([\w{_MARKS}]+)", re.UNICODE)


class Profile(NamedTuple):
    """What a real profile lookup told us about an author.

    `known` distinguishes "we looked and the account has no followers" from
    "we never looked" — without it, an unenriched author and a genuinely tiny
    one are the same row, and the second is a signal while the first is a gap.
    """
    pk: str = ""
    followers: int = 0
    verified: bool = False
    full_name: str = ""
    known: bool = False


UNKNOWN = Profile()


class AuthFailed(RuntimeError):
    """Every auth route was refused. Carries the per-route reasons, because
    "Instagram login failed" is not something an operator can act on and
    "IG_SESSIONID: login_required (session revoked)" is."""


def _silence_instagrapi_loggers() -> None:
    for name in (
        "instagrapi",
        "public_request",
        "private_request",
        "instagrapi.mixins.user",
        "instagrapi.mixins.private",
        "instagrapi.mixins.challenge",
        "instagrapi.mixins.auth",
        "instagrapi.mixins.public",
    ):
        l = logging.getLogger(name)
        l.setLevel(logging.CRITICAL)
        l.propagate = False


_silence_instagrapi_loggers()


def _auth_reason(exc: Exception) -> str:
    """Condense an instagrapi failure into the operator's next move.

    The raw exceptions are either a wall of Instagram's JSON or, worse,
    `TooManyRedirects` — which reads like a network fault and is in fact a
    revoked cookie bouncing off the login page.
    """
    text = str(exc)
    low = text.lower()
    if "toomanyredirects" in type(exc).__name__.lower() or "redirect" in low:
        return ("session cookie rejected — Instagram redirected to the login "
                "page (the cookie is expired or was revoked)")
    if "jsondecodeerror" in low or "expecting value" in low or "doctype html" in low:
        return ("session cookie rejected — Instagram redirected to a web login "
                "page (the session is expired or revoked)")
    if "challenge" in low or "checkpoint" in low:
        return ("Instagram wants a checkpoint cleared — open the account in "
                "the Instagram app on a trusted device, confirm it was you, "
                "then re-run `python -m app.crawlers.instagrapi_login`")
    if "login_required" in low or "logged out" in low:
        return "login_required — the session was revoked by Instagram"
    if "two_factor" in low or "2fa" in low:
        return ("two-factor is on for this account — run `python -m "
                "app.crawlers.instagrapi_login` once to answer the code")
    if "bad_password" in low or "incorrect" in low:
        return "IG_PASSWORD rejected"
    if "rate" in low or "429" in low or "wait a few minutes" in low:
        return "rate-limited by Instagram — backing off"
    return f"{type(exc).__name__}: {text[:160]}"


def _profile_of(info) -> Profile:
    """instagrapi User -> Profile."""
    return Profile(
        pk=str(getattr(info, "pk", "") or ""),
        followers=int(getattr(info, "follower_count", 0) or 0),
        verified=bool(getattr(info, "is_verified", False)),
        full_name=getattr(info, "full_name", "") or "",
        known=True,
    )


def _naive(ts: datetime | None) -> datetime | None:
    """instagrapi returns tz-aware datetimes; the rest of the pipeline stores
    naive UTC (see the Graph adapter's _iso)."""
    if ts is None:
        return None
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def _hashtags(text: str) -> list[str]:
    """Deduped, case-folded, order preserved — Instagram treats #Surat and
    #surat as one tag and so must the trend counter."""
    out, seen = [], set()
    for tag in _HASHTAG_RE.findall(text or ""):
        low = tag.lower()
        if low not in seen:
            seen.add(low)
            out.append(low)
    return out


def _media_urls(m) -> list[str]:
    """Every image/video on the media. A carousel keeps its frames in
    `resources`; a single photo or reel has only the top-level fields."""
    urls = []
    for res in (getattr(m, "resources", None) or []):
        u = getattr(res, "video_url", None) or getattr(res, "thumbnail_url", None)
        if u:
            urls.append(str(u))
    if not urls:
        for attr in ("video_url", "thumbnail_url"):
            if (u := getattr(m, attr, None)):
                urls.append(str(u))
                break
    return urls


def _reach(m) -> int:
    """Rough "how much did this travel" score, used only to rank which authors
    are worth a profile lookup this cycle."""
    return int(getattr(m, "like_count", 0) or 0) + int(getattr(m, "comment_count", 0) or 0)


def _rotate(items: list, cursor: int, size: int) -> tuple[list, int]:
    """A `size`-long slice starting where the last cycle stopped, wrapping
    round. Taking items[:size] every cycle — which is what this replaced —
    means the watchlist's 4th term onwards is never queried at all."""
    if not items or size <= 0:
        return [], cursor
    n = len(items)
    start = cursor % n
    take = min(size, n)
    return [items[(start + i) % n] for i in range(take)], start + take


class InstagrapiCollector(Collector):
    name = "Instagram (instagrapi)"
    min_interval_seconds = settings.IG_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._client = None  # instagrapi.Client, created lazily on first collect
        self._seen: set[str] = set()
        # username -> (resolved_at_monotonic, Profile). A returning account
        # costs no profile lookup until the entry ages out; without the TTL a
        # long-running process reports a follower count from whenever it first
        # booted, which for the seed pages is the number an analyst reads.
        self._accounts: dict[str, tuple[float, Profile]] = {}
        # pk -> (resolved_at_monotonic, Profile), for authors met via hashtags.
        self._profiles: dict[str, tuple[float, Profile]] = {}
        # username -> monotonic time a lookup failed (see MISSING_ACCOUNT_*).
        self._missing: dict[str, float] = {}
        # Where the last cycle's rotation stopped, per leg.
        self._tag_cursor = 0
        self._account_cursor = 0
        self._seed_cursor = 0
        # Why the last auth attempt failed, and when — see AUTH_RETRY_MINUTES.
        self._auth_error = ""
        self._auth_failed_at = 0.0

    def _has_credentials(self) -> bool:
        return bool(settings.IG_SESSIONID
                    or SESSION_FILE.exists()
                    or (settings.IG_USERNAME and settings.IG_PASSWORD))

    def is_configured(self) -> bool:
        if not self._has_credentials():
            return False
        if self._auth_error:
            if time.monotonic() - self._auth_failed_at < AUTH_RETRY_MINUTES * 60:
                return False
            # Window is up: clear the latch so the next tick tries again and
            # can report a *current* reason rather than a stale one.
            self._auth_error = ""
        return True

    def status_detail(self) -> str:
        return self._auth_error

    # ---- auth -------------------------------------------------------------

    def _auth_routes(self) -> list[tuple[str, object]]:
        """(label, authenticate) in preference order, credentials permitting.

        The saved dump has no login step of its own — `load_settings` below
        has already restored it, so the verification call *is* the attempt.
        """
        routes: list[tuple[str, object]] = []
        if settings.IG_SESSIONID:
            routes.append(("IG_SESSIONID",
                           lambda c: c.login_by_sessionid(settings.IG_SESSIONID)))
        if SESSION_FILE.exists():
            routes.append((SESSION_FILE.name, lambda c: None))
        if settings.IG_USERNAME and settings.IG_PASSWORD:
            routes.append(("IG_USERNAME/IG_PASSWORD",
                           lambda c: c.login(settings.IG_USERNAME,
                                             settings.IG_PASSWORD)))
        return routes

    def _login_sync(self):
        """Blocking login. Called only from a worker thread.

        Returns the first client that answers an authenticated private-API
        call, or raises AuthFailed carrying every route's reason.
        """
        from instagrapi import Client  # imported lazily: optional dependency

        routes = self._auth_routes()
        if not routes:
            raise AuthFailed("no instagrapi credentials — set IG_SESSIONID, or "
                             "IG_USERNAME/IG_PASSWORD, in backend/.env")

        failures: list[str] = []
        for label, authenticate in routes:
            # A fresh client per route: a refused cookie leaves authorization
            # data behind that would ride along on the next attempt.
            client = Client()
            # instagrapi sleeps this long between its own private-API calls.
            client.delay_range = [2, 5]

            # The dump is loaded first on every route, sessionid included, so
            # the device identity stays constant across runs — Instagram treats
            # a familiar device as less suspicious than a new one each time.
            if SESSION_FILE.exists():
                try:
                    client.load_settings(SESSION_FILE)
                except Exception as exc:  # corrupt dump mustn't block a login
                    log.warning("instagrapi: ignoring unreadable %s: %s",
                                SESSION_FILE.name, exc)

            try:
                authenticate(client)
                # The only thing that actually proves the session: one
                # authenticated call against the private API. Everything above
                # this line can "succeed" against a dead credential.
                client.account_info()
            except Exception as exc:
                reason = _auth_reason(exc)
                failures.append(f"{label}: {reason}")
                log.warning("instagrapi: %s refused — %s", label, reason)
                continue

            try:
                client.dump_settings(SESSION_FILE)
            except Exception as exc:  # a read-only volume must not kill a good session
                log.warning("instagrapi: could not save %s: %s", SESSION_FILE.name, exc)
            log.info("instagrapi: authenticated via %s", label)
            return client

        raise AuthFailed("; ".join(failures))

    async def _login(self):
        if self._client is None:
            self._client = await asyncio.to_thread(self._login_sync)
        return self._client

    # ---- mapping ----------------------------------------------------------

    def _fresh(self, kind: str, ident: str) -> bool:
        """First sighting of this media/comment? Kind-prefixed because a comment
        pk and a media pk are separate id spaces that can collide."""
        key = f"{kind}:{ident}"
        if not ident or key in self._seen:
            return False
        self._seen.add(key)
        return True

    def _media_to_post(self, m, city: str, profile: Profile = UNKNOWN) -> RawPost | None:
        mid = str(getattr(m, "pk", "") or getattr(m, "id", "") or "")
        text = (getattr(m, "caption_text", "") or "").strip()
        if not text or not self._fresh("media", mid):
            return None

        user = getattr(m, "user", None)
        handle = getattr(user, "username", None) or "instagram"
        loc = getattr(m, "location", None)
        # A geo-tagged post beats the seed account's configured city, and it
        # carries real coordinates the Graph adapter never gets.
        lat = float(getattr(loc, "lat", 0) or 0) if loc else 0.0
        lng = float(getattr(loc, "lng", 0) or 0) if loc else 0.0

        # A resolved profile is authoritative; the media's embedded user is a
        # UserShort whose is_verified is frequently absent (None -> False).
        verified = profile.verified if profile.known else bool(getattr(user, "is_verified", False))
        name = profile.full_name or getattr(user, "full_name", "") or handle

        code = getattr(m, "code", "")
        return RawPost(
            platform="Instagram",
            author_handle=handle,
            author_id=str(getattr(user, "pk", "") or profile.pk or ""),
            author_name=name,
            author_followers=profile.followers,
            author_verified=verified,
            text=text[:1000],
            hashtags=_hashtags(text),
            location=city,
            latitude=lat,
            longitude=lng,
            engagement={"likes": getattr(m, "like_count", 0) or 0, "shares": 0,
                        "comments": getattr(m, "comment_count", 0) or 0,
                        "views": int(getattr(m, "play_count", 0) or getattr(m, "view_count", 0) or 0)},
            url=f"https://www.instagram.com/p/{code}/" if code else "",
            media_urls=_media_urls(m),
            created_at=_naive(getattr(m, "taken_at", None)),
        )

    def _comment_to_post(self, c, parent_url: str, city: str) -> RawPost | None:
        text = (getattr(c, "text", "") or "").strip()
        cid = str(getattr(c, "pk", "") or "")
        if not text or not self._fresh("comment", cid):
            return None
        user = getattr(c, "user", None)
        handle = getattr(user, "username", None) or "instagram"
        # A commenter's own profile is never fetched: a busy thread is 20
        # strangers, and 20 lookups per media is exactly the traffic pattern
        # that gets the account challenged.
        pk = str(getattr(user, "pk", "") or "")
        cached = self._profiles.get(pk)
        profile = cached[1] if cached else UNKNOWN
        return RawPost(
            platform="Instagram",
            author_handle=handle,
            author_id=pk,
            author_name=profile.full_name or getattr(user, "full_name", "") or handle,
            author_followers=profile.followers,
            author_verified=(profile.verified if profile.known
                             else bool(getattr(user, "is_verified", False))),
            text=text[:1000],
            hashtags=_hashtags(text),
            # A comment inherits its parent's city; if the text names a target
            # city itself, ingestion's infer_city overrides this downstream.
            location=city,
            engagement={"likes": getattr(c, "like_count", 0) or 0, "shares": 0,
                        "comments": 0, "views": 0},
            url=f"{parent_url}c/{cid}/" if parent_url else "",
            created_at=_naive(getattr(c, "created_at_utc", None)),
        )

    # ---- users ------------------------------------------------------------

    def _cached_account(self, username: str) -> Profile | None:
        hit = self._accounts.get(username)
        if hit is None:
            return None
        age = time.monotonic() - hit[0]
        return hit[1] if age < settings.IG_PROFILE_TTL_HOURS * 3600 else None

    def _is_missing(self, username: str) -> bool:
        failed_at = self._missing.get(username)
        if failed_at is None:
            return False
        if time.monotonic() - failed_at < MISSING_ACCOUNT_RETRY_HOURS * 3600:
            return True
        del self._missing[username]  # give it another chance
        return False

    def _account_medias_sync(self, client, username: str, city: str,
                             limit: int) -> list[tuple]:
        """(media, city, Profile) for one account, or [] if it can't be read.

        Two calls at most: the profile (cached) and the media page. A private
        or deleted account raises on one of them and is remembered as missing
        so the next cycle doesn't pay for it again.
        """
        if self._is_missing(username):
            return []
        try:
            profile = self._cached_account(username)
            if profile is None:
                profile = _profile_of(client.user_info_by_username(username))
                self._accounts[username] = (time.monotonic(), profile)
                if profile.pk:
                    self._profiles[profile.pk] = (time.monotonic(), profile)
            medias = client.user_medias(profile.pk, amount=limit)
        except Exception as exc:
            self._missing[username] = time.monotonic()
            log.warning("instagrapi: account @%s unreadable (%s) — skipping for %dh",
                        username, exc, MISSING_ACCOUNT_RETRY_HOURS)
            return []
        return [(m, city, profile) for m in medias]

    def _seed_accounts_sync(self, client) -> list[tuple]:
        """The configured civic pages. Returns (media, city, Profile) so the
        caller can fetch comments against the right city without re-deriving
        it.

        Rotated, like the hashtag and watchlist legs, because the roster is no
        longer the handful of handles it started as. Reading every seed every
        cycle costs one profile lookup plus one media read per handle on the
        *private* API — at a few dozen handles that is the request pattern that
        earns a checkpoint, and a checkpointed account collects nothing from
        any city. A slice per cycle still covers the whole roster, just spread
        across the day: at the default 30-minute interval, 8 handles a cycle
        walks 48 in three hours. Set IG_SEEDS_PER_CYCLE to 0 for the old
        read-everything behaviour, which is only sane for a short list.
        """
        seeds = settings.IG_SEED_USERNAMES
        budget = settings.IG_SEEDS_PER_CYCLE
        if budget > 0:
            seeds, self._seed_cursor = _rotate(seeds, self._seed_cursor, budget)

        found: list[tuple] = []
        for username, city in seeds:
            found.extend(self._account_medias_sync(client, username, city, SEED_MEDIA_LIMIT))
        return found

    def _watched_accounts_sync(self, client) -> list[tuple]:
        """Handles an officer put on the watchlist.

        No city: the watchlist row says who to watch, never where they are, and
        guessing would put a Rajkot account's posts on the Surat map. Geo
        enrichment downstream reads the text instead.
        """
        budget = settings.IG_WATCHED_ACCOUNTS_PER_CYCLE
        if budget <= 0:
            return []
        try:
            handles = watched_accounts()
        except Exception as exc:  # a database blip must not cost us the cycle
            log.warning("instagrapi: watchlist accounts unavailable: %s", exc)
            return []
        usable = sorted({h.strip().lstrip("@").lower() for h in handles
                         if _IG_HANDLE_RE.match(h.strip().lstrip("@"))})
        slice_, self._account_cursor = _rotate(usable, self._account_cursor, budget)

        found: list[tuple] = []
        for username in slice_:
            found.extend(self._account_medias_sync(client, username, "", WATCHED_MEDIA_LIMIT))
        return found

    def _enrich_authors_sync(self, client, harvest: list[tuple]) -> list[tuple]:
        """Fill in the real profile behind media whose author we only know as a
        UserShort — i.e. everything the hashtag leg found.

        Cached profiles are applied for free; the lookup budget goes to the
        authors of the highest-engagement media, because an unknown account
        with a thousand likes on a communal post is the one whose reach an
        analyst is about to ask for.
        """
        by_pk: dict[str, int] = {}   # pk -> best reach seen this cycle
        for m, _city, profile in harvest:
            if profile.known:
                continue
            pk = str(getattr(getattr(m, "user", None), "pk", "") or "")
            if pk:
                by_pk[pk] = max(by_pk.get(pk, 0), _reach(m))

        ttl = settings.IG_PROFILE_TTL_HOURS * 3600
        now = time.monotonic()
        pending = []
        for pk in by_pk:
            hit = self._profiles.get(pk)
            if hit is None or now - hit[0] >= ttl:
                pending.append(pk)

        budget = max(0, settings.IG_PROFILE_LOOKUPS_PER_CYCLE)
        for pk in sorted(pending, key=lambda p: by_pk[p], reverse=True)[:budget]:
            try:
                self._profiles[pk] = (time.monotonic(), _profile_of(client.user_info(pk)))
            except Exception as exc:
                # Private, deactivated, or a rate limit. The post still gets
                # ingested — it just keeps its unknown-reach profile.
                log.warning("instagrapi: profile %s failed: %s", pk, exc)

        enriched: list[tuple] = []
        for m, city, profile in harvest:
            if not profile.known:
                pk = str(getattr(getattr(m, "user", None), "pk", "") or "")
                hit = self._profiles.get(pk)
                if hit is not None:
                    profile = hit[1]
            enriched.append((m, city, profile))
        return enriched

    # ---- collection strategies (all blocking, run in one worker thread) ----

    def _hashtag_medias(self, client, tag: str, amount: int) -> list:
        """Recent media for one tag: private mobile route first, public web
        route second.

        Instagram answers the private endpoint (tags/<name>/sections/) with
        `login_required` for sessions it does not fully trust — a fresh burner,
        or an account that has just cleared a checkpoint — while the public web
        GraphQL query, the one instagram.com itself runs, keeps answering.

        instagrapi has no fallback of its own to lean on here:
        hashtag_medias_recent is private-only, and hashtag_medias_paginated
        re-raises LoginRequired (a PrivateError) before it ever reaches its
        public branch. Hence this. The exception is matched on its text because
        instagrapi is an optional dependency — importing its exception classes
        at module scope would make the whole registry unimportable without it.
        """
        try:
            return client.hashtag_medias_recent(tag, amount=amount)
        except Exception as exc:
            if "login_required" not in str(exc).lower():
                raise
            log.info("instagrapi: #%s refused on the private route, trying the "
                     "public one", tag)
            # Carries the session cookie over to the public client, which is
            # otherwise anonymous and gets redirected to a login page.
            client.inject_sessionid_to_public()
            medias, _cursor = client.hashtag_medias_paginated_gql(tag, amount=amount)
            return medias

    def _hashtags_sync(self, client, watch_terms: list[str]) -> list[tuple]:
        found: list[tuple] = []
        # A tag is one token by definition, so multi-word watchlist keywords
        # ("bandh call") are not hashtags and are skipped. isalnum() is
        # Unicode-aware, so Gujarati and Devanagari tags pass.
        tags = [t.lstrip("#") for t in watch_terms if t and t.replace("#", "").isalnum()]
        slice_, self._tag_cursor = _rotate(tags, self._tag_cursor,
                                           settings.IG_HASHTAGS_PER_CYCLE)
        for tag in slice_:
            try:
                medias = self._hashtag_medias(client, tag, HASHTAG_MEDIA_LIMIT)
            except Exception as exc:
                log.warning("instagrapi: hashtag #%s failed: %s", tag, exc)
                continue
            # No city — the post is on-scope by virtue of matching a watchlist
            # tag, and geo enrichment happens downstream. No profile either;
            # _enrich_authors_sync fills what it can afford.
            found.extend((m, "", UNKNOWN) for m in medias)
        return found

    def _comments_sync(self, client, harvest: list[tuple],
                       posts_by_media: dict[str, RawPost]) -> list[RawPost]:
        """Comment threads for the most-discussed media this cycle.

        Every media costs one more private-API call, and instagrapi sleeps
        2-5s between calls, so pulling comments for all ~50 media a cycle
        would mean minutes of hammering and a fast route to a challenge.
        Budget goes to the media with the most comments — the loudest threads
        are also the ones an analyst would open first.
        """
        budget = settings.IG_COMMENTS_MAX_MEDIA_PER_CYCLE
        if budget <= 0:
            return []
        ranked = sorted(
            (t for t in harvest if (getattr(t[0], "comment_count", 0) or 0) > 0),
            key=lambda t: getattr(t[0], "comment_count", 0) or 0,
            reverse=True,
        )[:budget]

        out: list[RawPost] = []
        for m, city, _profile in ranked:
            mid = str(getattr(m, "pk", "") or getattr(m, "id", "") or "")
            parent = posts_by_media.get(mid)
            if parent is None:  # caption was empty or already seen — skip
                continue
            try:
                comments = client.media_comments(
                    str(getattr(m, "id", "") or mid),
                    amount=settings.IG_COMMENTS_PER_MEDIA,
                )
            except Exception as exc:
                # Comments disabled, deleted media, or a rate-limit — one dead
                # thread must not cost us the others.
                log.warning("instagrapi: comments for %s failed: %s", mid, exc)
                continue
            for c in comments:
                if (post := self._comment_to_post(c, parent.url, city)):
                    out.append(post)
        return out

    def _collect_sync(self, client, watch_terms: list[str]) -> list[RawPost]:
        harvest = self._seed_accounts_sync(client)
        harvest.extend(self._watched_accounts_sync(client))
        harvest.extend(self._hashtags_sync(client, watch_terms))
        harvest = self._enrich_authors_sync(client, harvest)

        posts: list[RawPost] = []
        posts_by_media: dict[str, RawPost] = {}
        for m, city, profile in harvest:
            if (post := self._media_to_post(m, city, profile)):
                posts.append(post)
                mid = str(getattr(m, "pk", "") or getattr(m, "id", "") or "")
                posts_by_media[mid] = post

        comments = self._comments_sync(client, harvest, posts_by_media)
        posts.extend(comments)
        log.info("instagrapi: %d media + %d comments", len(posts) - len(comments), len(comments))
        return posts

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        try:
            client = await self._login()
            return await asyncio.to_thread(self._collect_sync, client, watch_terms)
        except AuthFailed as exc:
            # Latched, so the adapter reports offline and stops retrying for a
            # while. A credential Instagram has refused will not start working
            # because we asked again ninety seconds later, and repeated failed
            # logins are exactly the pattern that escalates a soft block.
            self._client = None
            self._auth_error = str(exc)
            self._auth_failed_at = time.monotonic()
            log.warning("instagrapi: Instagram is OFFLINE — no auth route worked "
                        "(%s). Retrying in %d minutes.", exc, AUTH_RETRY_MINUTES)
            return []
        except Exception as exc:
            self._client = None  # force a fresh login next tick after any failure
            log.warning("instagrapi Instagram collect failed: %s", exc)
            return []
