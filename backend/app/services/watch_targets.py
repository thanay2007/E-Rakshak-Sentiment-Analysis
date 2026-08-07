"""Cached reads of the watchlist for the collection path.

Two different things are read out of the watchlist on every crawl tick:

  * **terms** — keyword and hashtag rows, handed to every collector's
    ``collect(watch_terms)`` as the search vocabulary for that cycle.
  * **accounts** — the handles an officer put under watch. These never reached
    a collector before, so a watched account was only ever monitored by
    accident, when it happened to post something matching a keyword. Adapters
    that can read an account directly (instagrapi, so far) read this list.

Both live here rather than in scheduler.py because a crawler needs the second
one, and importing the scheduler from a crawler would close the import loop
(scheduler → registry → crawlers).

Read fresh on every tick these cost a database round trip several times a
minute for lists that change when an officer edits the watchlist — perhaps
twice a day. Against a remote database that was one of the steadier drains on
the connection pool, hence the TTL, and the explicit invalidation from the
watchlist router so an edit still lands on the next tick.
"""
import time

from sqlmodel import select

from app.database import session_scope
from app.models import WatchlistItem

WATCH_TERM_TTL_SECONDS = 60.0

# kind -> (cached_at_monotonic, values)
_cache: dict[str, tuple[float, list[str]]] = {}


def _values(kinds: list[str], cache_key: str) -> list[str]:
    now = time.monotonic()
    hit = _cache.get(cache_key)
    if hit is not None and now - hit[0] < WATCH_TERM_TTL_SECONDS:
        return hit[1]
    with session_scope() as s:
        items = s.exec(
            select(WatchlistItem).where(
                WatchlistItem.active == True,  # noqa: E712
                WatchlistItem.kind.in_(kinds),
            )
        ).all()
    values = [i.value for i in items]
    _cache[cache_key] = (now, values)
    return values


def watch_terms() -> list[str]:
    """Keyword + hashtag rows — the search vocabulary handed to collectors."""
    return _values(["keyword", "hashtag"], "terms")


def watched_accounts() -> list[str]:
    """Watched handles, as the officer typed them.

    Deliberately unfiltered: the watchlist has no platform column, so a row
    here may be an X handle, a Telegram channel or a wildcard pattern like
    ``desh_sachai_*``. Each adapter decides what it can act on — see
    instagrapi_ig._IG_HANDLE_RE.
    """
    return _values(["account"], "accounts")


def invalidate() -> None:
    """Called when the watchlist changes, so an edit takes effect on the next
    tick rather than whenever the cache happens to expire."""
    _cache.clear()
