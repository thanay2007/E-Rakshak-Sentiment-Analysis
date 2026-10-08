"""Instagram account feeds — a Python port of pgrimaud/instagram-user-feed
(github.com/pgrimaud/instagram-user-feed, MIT).

That library is PHP and this backend is Python, so — as with instagram4j
before it (see instagram_public.py) — its request recipe is ported rather than
vendored: the endpoints, headers, app id and GraphQL query hashes below are
its findings, and the response envelopes are read exactly the way its
hydrators read them.

What it reads, per account:

  * **profile + first page of posts** — ``i.instagram.com/api/v1/users/
    web_profile_info/?username=…`` with the web app id header
    (``JsonProfileDataFeedV2`` + ``ProfileHydrator``). One request returns the
    follower count, verified/private flags *and* the newest twelve posts.
  * **more posts** — ``graphql/query/?query_hash=42323d…`` with
    ``{id, first, after}`` (``JsonMediasDataFeed``), when an account's read
    asks for more than the first page.
  * **comments** — with a live session, the web app's own
    ``api/v1/media/<id>/comments/`` route, which also carries a preview of
    the replies under each comment. The library's
    ``graphql/query/?query_hash=33ba35…`` (``JsonMediaCommentsFeed``) is the
    fallback; Instagram has been retiring query hashes, so it may be dead.

Auth is the library's ``loginWithCookies``: if IG_SESSIONID is set, its
``sessionid`` cookie rides on every request, which is what keeps
web_profile_info from rate-limiting after a handful of calls. Without it the
same routes are tried signed out. A cookie Instagram has logged out (it
answers with a redirect to /accounts/login/) is dropped for the life of the
process and the cycle carries on signed out, with the reason on the sources
panel, until a fresh one is pasted in. The library's password login is not
ported — a scripted password login is what gets an account checkpointed, and
`python -m app.crawlers.instagrapi_login` already covers it properly.

Posts with no caption are not emitted (there is no text to score) but their
comment threads are still read: on a photo post the grievance is in the
comments.

Query hashes are Instagram's and retire without notice. A retired one answers
with an error or an empty envelope; every caller here treats that as "no data
this cycle", never as fatal, and the profile route (which carries the posts)
does not depend on either hash.

Discovery of accounts nobody listed still comes from the signed-out hashtag
route in instagram_public.py, whose authors are written to the shared
roster and read here on later cycles.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime, timezone

import requests

from app.config import settings
from app.crawlers import instagram_public, roster
from app.crawlers.base import Collector
from app.crawlers.common import extract_hashtags
from app.crawlers.common import rotate as _rotate
from app.schemas import RawPost
from app.services.watch_targets import watched_accounts

log = logging.getLogger("sentinel.crawlers")

# ── the library's constants (src/Instagram/Utils/*.php) ─────────────────────

URL_BASE = "https://www.instagram.com/"
URL_API_BASE = "https://i.instagram.com/"
#: InstagramHelper::QUERY_HASH_MEDIAS / QUERY_HASH_COMMENTS
QUERY_HASH_MEDIAS = "42323d64886122307be10013ad2dcc44"
QUERY_HASH_COMMENTS = "33ba35852cb50da46f5b5e889df7d159"
#: The instagram.com web app's id, sent by JsonProfileDataFeedV2.
IG_APP_ID = "936619743392459"
#: OptionHelper::$USER_AGENT / $LOCALE
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36")
LOCALE = "en-EN"
TIMEOUT = 25

# ── collection budgets ─────────────────────────────────────────────────────

SEED_MEDIA_LIMIT = 12
WATCHED_MEDIA_LIMIT = 8
DISCOVERED_MEDIA_LIMIT = 6
HASHTAG_MEDIA_LIMIT = 15
#: A handle that failed is not retried for this long — see instagrapi_ig.py.
MISSING_ACCOUNT_RETRY_HOURS = 6
#: How long the whole route stays parked after Instagram answers 429 or asks
#: for a checkpoint. Re-asking is what turns a soft limit into a block.
RATE_LIMIT_COOLDOWN_MINUTES = 90
#: Pause between requests inside one cycle, in seconds. The library itself
#: has none; a loop over a roster without one is a burst Instagram notices.
REQUEST_GAP = (2.0, 5.0)

_IG_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


class RateLimited(RuntimeError):
    """Instagram answered 429 — stop asking for a while."""


class CheckpointRequired(RuntimeError):
    """The session cookie was challenged (InstagramAuthException upstream)."""


class SessionExpired(RuntimeError):
    """The IG_SESSIONID cookie is logged out — Instagram redirected to its
    login page. Not a rate limit: carrying on signed out is fine."""


class AccountUnavailable(RuntimeError):
    """The account does not exist or will not be served — a verdict about the
    account, not about the route."""


# ── the port ───────────────────────────────────────────────────────────────

def make_session(sessionid: str = "") -> requests.Session:
    """AbstractDataFeed's headers, plus the session cookie if there is one."""
    s = requests.Session()
    s.headers.update({
        "user-agent": USER_AGENT,
        "accept-language": LOCALE,
        "x-requested-with": "XMLHttpRequest",
    })
    if sessionid:
        s.cookies.set("sessionid", sessionid, domain=".instagram.com")
    return s


def _fetch_json(session: requests.Session, url: str, *, params: dict | None = None,
                headers: dict | None = None) -> dict:
    """AbstractDataFeed::fetchJsonDataFeed, with Instagram's refusals typed."""
    response = session.get(url, params=params, headers=headers, timeout=TIMEOUT)
    body = response.text or ""
    if response.status_code == 429:
        raise RateLimited("Instagram rate-limited the user-feed route (HTTP 429)")
    if '"checkpoint_required"' in body or "/challenge/" in str(response.url):
        raise CheckpointRequired("Instagram asked the session for a checkpoint")
    cookies = getattr(session, "cookies", None)
    if "/accounts/login" in str(response.url) and cookies is not None \
            and cookies.get("sessionid"):
        raise SessionExpired("IG_SESSIONID is logged out — Instagram redirected it "
                             "to the login page")
    if response.status_code == 404:
        raise AccountUnavailable("not found")
    if not body.lstrip().startswith("{"):
        # The login wall is an HTML page with status 200.
        raise RateLimited(f"Instagram served a non-JSON page "
                          f"(HTTP {response.status_code}) — login wall")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"unreadable JSON from Instagram: {exc}") from exc


def fetch_profile(session: requests.Session, username: str) -> dict:
    """JsonProfileDataFeedV2::fetchData — the profile's ``data.user`` object."""
    data = _fetch_json(session, f"{URL_API_BASE}api/v1/users/web_profile_info/",
                       params={"username": username},
                       headers={"x-ig-app-id": IG_APP_ID})
    user = (data.get("data") or {}).get("user")
    if not user:
        raise AccountUnavailable(f"Instagram id {username} does not exist")
    return user


def fetch_more_medias(session: requests.Session, user_id: str, end_cursor: str,
                      limit: int = 12) -> dict:
    """JsonMediasDataFeed::fetchData — the next page of an account's posts.

    Returns ``edge_owner_to_timeline_media`` ({edges, page_info}) or {}.
    """
    variables = {"id": str(user_id), "first": limit, "after": end_cursor}
    data = _fetch_json(session, f"{URL_BASE}graphql/query/", params={
        "query_hash": QUERY_HASH_MEDIAS, "variables": json.dumps(variables)})
    user = (data.get("data") or {}).get("user") or {}
    return user.get("edge_owner_to_timeline_media") or {}


def _v1_comment(c: dict, reply_to: str = "") -> dict:
    """A v1 comment in the GraphQL node shape the rest of this module reads."""
    user = c.get("user") or {}
    return {"id": str(c.get("pk") or c.get("id") or ""),
            "text": c.get("text") or "",
            "created_at": c.get("created_at_utc") or c.get("created_at"),
            "owner": {"id": str(user.get("pk") or user.get("id") or ""),
                      "username": user.get("username") or "",
                      "is_verified": bool(user.get("is_verified"))},
            "edge_liked_by": {"count": int(c.get("comment_like_count") or 0)},
            "replies": int(c.get("child_comment_count") or 0),
            "reply_to": reply_to}


def fetch_comments_v1(session: requests.Session, media_id: str, limit: int = 12) -> list[dict]:
    """The web app's comments route — needs a live session. Returns top-level
    comments and the replies Instagram previews under them, as nodes."""
    data = _fetch_json(session, f"{URL_BASE}api/v1/media/{media_id}/comments/",
                       params={"can_support_threading": "true",
                               "permalink_enabled": "false"},
                       headers={"x-ig-app-id": IG_APP_ID})
    nodes: list[dict] = []
    for c in (data.get("comments") or [])[:limit]:
        if not isinstance(c, dict):
            continue
        parent = _v1_comment(c)
        nodes.append(parent)
        nodes += [_v1_comment(r, reply_to=parent["id"])
                  for r in c.get("preview_child_comments") or [] if isinstance(r, dict)]
    return nodes


def fetch_comments(session: requests.Session, shortcode: str, limit: int = 12,
                   media_id: str = "") -> list[dict]:
    """Comment nodes for one post: the v1 route when the session is live, the
    library's query hash otherwise (or when v1 fails).

    Each node: {id, text, created_at, owner{id, username, is_verified},
    edge_liked_by{count}?, reply_to?}.
    """
    cookies = getattr(session, "cookies", None)
    if media_id and cookies is not None and cookies.get("sessionid"):
        try:
            return fetch_comments_v1(session, media_id, limit)
        except (RateLimited, CheckpointRequired, SessionExpired):
            raise
        except Exception as exc:
            log.debug("user feed: v1 comments for %s failed (%s) — trying the "
                      "query hash", shortcode, exc)
    return fetch_comments_graphql(session, shortcode, limit)


def fetch_comments_graphql(session: requests.Session, shortcode: str,
                           limit: int = 12) -> list[dict]:
    """JsonMediaCommentsFeed::fetchData — comment nodes for one post."""
    variables = {"shortcode": shortcode, "first": limit}
    data = _fetch_json(session, f"{URL_BASE}graphql/query/", params={
        "query_hash": QUERY_HASH_COMMENTS, "variables": json.dumps(variables)})
    media = (data.get("data") or {}).get("shortcode_media") or {}
    edges = (media.get("edge_media_to_comment") or {}).get("edges") or []
    return [e.get("node") or {} for e in edges if isinstance(e, dict)]


def profile_summary(user: dict) -> dict:
    """ProfileHydrator::hydrateProfile + hydrateMedias, as a plain dict."""
    timeline = user.get("edge_owner_to_timeline_media") or {}
    return {
        "id": str(user.get("id") or ""),
        "username": user.get("username") or "",
        "full_name": user.get("full_name") or "",
        "followers": int((user.get("edge_followed_by") or {}).get("count", 0) or 0),
        "verified": bool(user.get("is_verified")),
        "private": bool(user.get("is_private")),
        "media_count": int(timeline.get("count", 0) or 0),
        "medias": [e.get("node") or {} for e in timeline.get("edges") or []],
        "end_cursor": (timeline.get("page_info") or {}).get("end_cursor") or "",
    }


# ── the collector ──────────────────────────────────────────────────────────

class InstagramUserFeedCollector(Collector):
    """Instagram posts from account feeds, via the instagram-user-feed port.

    Preferred over instagrapi (see registry.py) while IG_USERFEED_ENABLED is
    true: it reads public web routes with a cookie at most, so there is no
    private-API login to be challenged. Legs, each on its own rotation budget —
    the same budgets and roster the instagrapi adapter uses, so switching
    between the two changes how accounts are read, never which:

      * seed accounts (IG_SEED_USERNAMES)
      * accounts an officer put on the watchlist
      * accounts discovered earlier (backend/discovered_accounts.json)
      * signed-out hashtag media, which is also how new accounts are found
      * comment threads under the most-discussed posts of the cycle
    """

    name = "Instagram (user feed)"
    min_interval_seconds = settings.IG_MIN_INTERVAL_SECONDS
    timeout_seconds = 120 + 6 * (
        settings.IG_SEEDS_PER_CYCLE
        + settings.IG_WATCHED_ACCOUNTS_PER_CYCLE
        + settings.IG_DISCOVERED_ACCOUNTS_PER_CYCLE
        + settings.IG_HASHTAGS_PER_CYCLE
        + settings.IG_COMMENTS_MAX_MEDIA_PER_CYCLE)

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._missing: dict[str, float] = {}
        self._seed_cursor = 0
        self._watched_cursor = 0
        self._discovered_cursor = 0
        self._tag_cursor = 0
        self._parked_at = 0.0
        self._error = ""
        #: The IG_SESSIONID value Instagram answered with its login page.
        self._dead_sessionid = ""
        #: Parent posts whose thread was read this cycle (by object id).
        self._threads_read: set[int] = set()

    def is_configured(self) -> bool:
        if not settings.IG_USERFEED_ENABLED:
            return False
        if self._parked_at:
            if time.monotonic() - self._parked_at < RATE_LIMIT_COOLDOWN_MINUTES * 60:
                return False
            self._parked_at = 0.0  # cooldown over — try again, keep the reason
        return True

    def status_detail(self) -> str:
        return self._error

    # ── helpers ────────────────────────────────────────────────────────────

    def _fresh(self, kind: str, ident: str) -> bool:
        key = f"{kind}:{ident}"
        if not ident or key in self._seen:
            return False
        self._seen.add(key)
        return True

    def _is_missing(self, username: str) -> bool:
        failed_at = self._missing.get(username)
        if failed_at is None:
            return False
        if time.monotonic() - failed_at < MISSING_ACCOUNT_RETRY_HOURS * 3600:
            return True
        del self._missing[username]
        return False

    @staticmethod
    def _pause() -> None:
        time.sleep(random.uniform(*REQUEST_GAP))

    def _account(self, session: requests.Session, username: str, city: str,
                 limit: int, discovered: bool = False) -> list[tuple[dict, RawPost, bool]]:
        """(media node, RawPost, emit) for one account's newest posts. `emit`
        is False for a post with no caption: it is kept only as the parent of
        its comment thread.

        RateLimited / CheckpointRequired / SessionExpired propagate — they are
        about the route, and the cycle has to stop or change course. Anything
        else is about this account.
        """
        if self._is_missing(username):
            return []
        try:
            info = profile_summary(fetch_profile(session, username))
            self._pause()
            if info["private"]:
                raise AccountUnavailable("private account")
            if discovered and info["followers"] < settings.IG_DISCOVERED_MIN_FOLLOWERS:
                self._missing[username] = time.monotonic()
                roster.prune("instagram", [username],
                             f"@{username} has {info['followers']} followers")
                return []
            nodes = info["medias"][:limit]
            if len(nodes) < limit and info["end_cursor"] and info["id"]:
                try:
                    more = fetch_more_medias(session, info["id"], info["end_cursor"],
                                             limit - len(nodes))
                    nodes += [e.get("node") or {} for e in more.get("edges") or []]
                    self._pause()
                except (RateLimited, CheckpointRequired, SessionExpired):
                    raise
                except Exception as exc:  # a retired query hash costs page two only
                    log.debug("user feed: more medias for @%s failed: %s", username, exc)
        except (RateLimited, CheckpointRequired, SessionExpired):
            raise
        except AccountUnavailable as exc:
            self._missing[username] = time.monotonic()
            if discovered:
                roster.prune("instagram", [username], f"unreadable ({exc})")
            log.info("user feed: @%s unavailable (%s) — skipping for %dh",
                     username, exc, MISSING_ACCOUNT_RETRY_HOURS)
            return []
        except Exception as exc:
            # Network trouble says nothing about the account — skip it this
            # time without pruning it (the lesson recorded in instagrapi_ig.py).
            self._missing[username] = time.monotonic()
            log.warning("user feed: @%s unreadable (%s)", username, exc)
            return []

        out = []
        for node in nodes:
            handle = info["username"] or username
            hit = instagram_public._to_post(
                node, city, handle=handle, followers=info["followers"],
                verified=info["verified"], name=info["full_name"])
            emit = hit is not None
            if hit is None:
                # No caption: nothing to score, but its comments still count.
                hit = instagram_public._to_post(
                    {**node, "caption": {"text": "(no caption)"}}, city, handle=handle,
                    followers=info["followers"], verified=info["verified"],
                    name=info["full_name"])
                if hit is None:
                    continue
            mid, post = hit
            if not post.author_id:
                post.author_id = info["id"]
            if self._fresh("media", mid):
                out.append((node, post, emit))
        return out

    def _comment_to_post(self, node: dict, parent: RawPost) -> RawPost | None:
        """CommentHydrator::hydrateComment → RawPost, the convention every
        adapter here uses: a comment is a post in its own right."""
        text = (node.get("text") or "").strip()
        cid = str(node.get("id") or "")
        if not text or not self._fresh("comment", cid):
            return None
        owner = node.get("owner") or {}
        handle = owner.get("username") or "instagram"
        created = None
        if node.get("created_at"):
            try:
                created = datetime.fromtimestamp(int(node["created_at"]),
                                                 tz=timezone.utc).replace(tzinfo=None)
            except (ValueError, OSError, OverflowError):
                created = None
        return RawPost(
            platform="Instagram",
            author_handle=handle,
            author_id=str(owner.get("id") or ""),
            author_name=handle,
            author_followers=0,  # a commenter's profile is never fetched
            author_verified=bool(owner.get("is_verified")),
            text=text[:1000],
            hashtags=extract_hashtags(text),
            location=parent.location,
            engagement={"likes": int((node.get("edge_liked_by") or {}).get("count", 0) or 0),
                        "shares": 0, "comments": 0, "views": 0},
            url=f"{parent.url}c/{cid}/" if parent.url else "",
            created_at=created,
        )

    # ── legs ───────────────────────────────────────────────────────────────

    def _accounts_leg(self, session: requests.Session,
                      harvest: list[tuple[dict, RawPost, bool]]) -> None:
        """Seed, watched and discovered accounts, appended to `harvest` as they
        are read — so a refusal halfway through keeps what came before it."""

        seeds = settings.IG_SEED_USERNAMES
        if settings.IG_SEEDS_PER_CYCLE > 0:
            seeds, self._seed_cursor = _rotate(seeds, self._seed_cursor,
                                               settings.IG_SEEDS_PER_CYCLE)
        for username, city in seeds:
            harvest += self._account(session, username, city, SEED_MEDIA_LIMIT)

        if settings.IG_WATCHED_ACCOUNTS_PER_CYCLE > 0:
            try:
                handles = watched_accounts()
            except Exception as exc:
                log.warning("user feed: watchlist accounts unavailable: %s", exc)
                handles = []
            usable = sorted({h.strip().lstrip("@").lower() for h in handles
                             if _IG_HANDLE_RE.match(h.strip().lstrip("@"))})
            slice_, self._watched_cursor = _rotate(
                usable, self._watched_cursor, settings.IG_WATCHED_ACCOUNTS_PER_CYCLE)
            for username in slice_:
                harvest += self._account(session, username, "", WATCHED_MEDIA_LIMIT)

        if settings.IG_DISCOVERED_ACCOUNTS_PER_CYCLE > 0:
            seeded = {u.casefold() for u, _ in settings.IG_SEED_USERNAMES}
            pool = [(h, c) for h, c in roster.handles("instagram")
                    if h.casefold() not in seeded and _IG_HANDLE_RE.match(h)]
            slice_, self._discovered_cursor = _rotate(
                pool, self._discovered_cursor, settings.IG_DISCOVERED_ACCOUNTS_PER_CYCLE)
            for username, city in slice_:
                harvest += self._account(session, username, city,
                                         DISCOVERED_MEDIA_LIMIT, discovered=True)

    def _hashtag_leg(self, watch_terms: list[str]) -> list[RawPost]:
        """Signed-out hashtag media — the one leg that reaches accounts nobody
        listed, and so also how the roster grows."""
        budget = settings.IG_HASHTAGS_PER_CYCLE
        if budget <= 0:
            return []
        tags = [t.lstrip("#") for t in watch_terms if t and t.replace("#", "").isalnum()]
        tags = list(dict.fromkeys([c.lower() for c in settings.TARGET_CITIES] + tags))
        slice_, self._tag_cursor = _rotate(tags, self._tag_cursor, budget)
        public = instagram_public._session()
        posts: list[RawPost] = []
        for tag in slice_:
            try:
                found = instagram_public.hashtag_medias(tag, HASHTAG_MEDIA_LIMIT, public)
            except instagram_public.PublicRateLimited:
                log.info("user feed: signed-out hashtag route rate-limited")
                break
            except Exception as exc:
                log.warning("user feed: #%s failed: %s", tag, exc)
                continue
            posts += [p for mid, p in found if self._fresh("media", mid)]
            self._pause()
        if posts:
            roster.add("instagram", [
                {"handle": p.author_handle, "city": "", "name": p.author_name,
                 "source": "ig-public-hashtag"} for p in posts
                if _IG_HANDLE_RE.match(p.author_handle)])
        return posts

    def _comments_leg(self, session: requests.Session,
                      harvest: list[tuple[dict, RawPost, bool]],
                      out: list[RawPost]) -> None:
        """Comments (and previewed replies) under the cycle's most-discussed
        posts, appended to `out` as they are read."""
        budget = settings.IG_COMMENTS_MAX_MEDIA_PER_CYCLE
        if budget <= 0:
            return
        ranked = sorted((h for h in harvest if h[1].engagement.get("comments", 0) > 0
                         and id(h[1]) not in self._threads_read),
                        key=lambda h: h[1].engagement.get("comments", 0),
                        reverse=True)[:budget]
        for node, parent, _ in ranked:
            code = node.get("shortcode") or node.get("code")
            if not code:
                continue
            try:
                comments = fetch_comments(session, code, settings.IG_COMMENTS_PER_MEDIA,
                                          media_id=str(node.get("id") or node.get("pk") or ""))
            except (RateLimited, CheckpointRequired, SessionExpired):
                raise
            except Exception as exc:
                log.warning("user feed: comments for %s failed: %s", code, exc)
                continue
            self._threads_read.add(id(parent))
            out += [p for c in comments if (p := self._comment_to_post(c, parent))]
            self._pause()

    # ── cycle ──────────────────────────────────────────────────────────────

    def _cookie(self) -> str:
        """IG_SESSIONID, unless Instagram has already said it is logged out."""
        sessionid = settings.IG_SESSIONID
        return "" if sessionid and sessionid == self._dead_sessionid else sessionid

    def _collect_sync(self, watch_terms: list[str]) -> list[RawPost]:
        harvest: list[tuple[dict, RawPost, bool]] = []
        comments: list[RawPost] = []
        self._threads_read = set()
        signed_out_note = (self._error if self._dead_sessionid
                           and self._dead_sessionid == settings.IG_SESSIONID else "")
        for _attempt in range(2):
            session = make_session(self._cookie())
            try:
                self._accounts_leg(session, harvest)
                self._comments_leg(session, harvest, comments)
                self._error = signed_out_note
                break
            except SessionExpired as exc:
                # Not a refusal of the route: drop the cookie and read the
                # rest of the cycle signed out. Accounts and threads already
                # read are remembered, so the retry only reads what is left.
                self._dead_sessionid = settings.IG_SESSIONID
                signed_out_note = (f"{exc}. Reading signed out (fewer accounts, no "
                                   "comments) until a fresh sessionid cookie from a "
                                   "logged-in browser is put in IG_SESSIONID.")
                self._error = signed_out_note
                log.warning("user feed: %s — continuing signed out", exc)
            except (RateLimited, CheckpointRequired) as exc:
                # Keep what was read before the refusal; park the route.
                self._error = f"{exc}. {signed_out_note}".strip()
                self._parked_at = time.monotonic()
                log.warning("user feed: %s — parking Instagram for %d minutes "
                            "(posts already read this cycle are kept)",
                            exc, RATE_LIMIT_COOLDOWN_MINUTES)
                break
        tagged = self._hashtag_leg(watch_terms)
        posts = [p for _, p, emit in harvest if emit] + comments + tagged
        log.info("user feed: %d account posts + %d comments + %d hashtag posts",
                 len(posts) - len(comments) - len(tagged), len(comments), len(tagged))
        return posts

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        try:
            return await asyncio.to_thread(self._collect_sync, watch_terms)
        except Exception as exc:
            log.warning("Instagram user-feed collect failed: %s", exc)
            return []
