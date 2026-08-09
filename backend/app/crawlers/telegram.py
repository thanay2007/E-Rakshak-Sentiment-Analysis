"""Telegram adapter — official MTProto API (Telethon), keyless fallback to
Telegram's own public channel preview pages (t.me/s/<channel>).

With TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_SESSION_STRING set it talks
to Telegram's official client API (credentials from my.telegram.org). That mode
reads every seed channel in one pass instead of round-robining a few per cycle,
and reaches public channels whose t.me/s preview page is disabled.

Note there is no keyword search at collection time in either mode: Telegram
exposes no public message-search API (messages.searchGlobal covers only chats
the account has joined). Widening coverage means adding seed channels, which
telegram_discover.py finds via contacts.Search.

Without credentials it reads t.me/s/<channel>, the public HTML preview Telegram
serves for most public channels with no auth at all. Live and complete for
post text, views and timestamps, but only covers channels that leave the
preview page enabled.

The Bot API is deliberately not used: a bot only sees channels where it has
been made an admin, which is useless for open-source monitoring.

Both modes share the seed-channel strategy (TELEGRAM_CHANNELS, optional :City
suffix); posts with no configured city are geo-tagged by infer_city() over the
text, same as the other city-anchored crawlers.
"""
import asyncio
import html as html_lib
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from app.config import BASE_DIR, settings
from app.crawlers.base import Collector
from app.ml.geo import infer_city
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

PREVIEW_BASE = "https://t.me/s"
# t.me/s only renders for browser UAs — an honest desktop UA is what makes it work.
PREVIEW_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CHANNELS_PER_CYCLE = 3   # round-robin slice; t.me throttles bursts
SESSION_FILE = BASE_DIR / "telegram_session"

_MSG_RE = re.compile(
    r'<div class="tgme_widget_message[^"]*"[^>]*data-post="([^"]+)"(.*?)(?=<div class="tgme_widget_message\b|\Z)',
    re.S)
_TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME_RE = re.compile(r'<time[^>]+datetime="([^"]+)"')
_VIEWS_RE = re.compile(r'<span class="tgme_widget_message_views">([^<]+)</span>')
_AUTHOR_RE = re.compile(r'<span class="tgme_widget_message_from_author"[^>]*>(.*?)</span>', re.S)
_PHOTO_RE = re.compile(r"background-image:url\('([^']+)'\)")
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    """Message HTML -> plain text. <br> and </div> are the only line breaks
    Telegram emits inside a message body; everything else is inline markup."""
    text = re.sub(r"<br\s*/?>", "\n", raw)
    text = _TAG_RE.sub("", text)
    return re.sub(r"[ \t]+", " ", html_lib.unescape(text)).strip()


def _views(raw: str | None) -> int:
    """'1.2K' / '3.4M' -> int. Telegram only ever shows these two suffixes."""
    if not raw:
        return 0
    raw = raw.strip().upper()
    mult = {"K": 1_000, "M": 1_000_000}.get(raw[-1:], 1)
    try:
        return int(float(raw[:-1] if mult > 1 else raw) * mult)
    except ValueError:
        return 0


def _iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


class TelegramCollector(Collector):
    name = "Telegram"
    min_interval_seconds = settings.CRAWL_MIN_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._client = None       # telethon.TelegramClient, created lazily
        self._cursor = 0          # round-robin position over the seed channels
        self._mtproto_until = 0.0  # FloodWait cooldown: monotonic deadline

    def is_configured(self) -> bool:
        # Always on: MTProto when credentials exist, public previews otherwise.
        return bool(settings.TELEGRAM_CHANNELS)

    def _make_post(self, *, key: str, channel: str, city: str, text: str,
                   views: int, forwards: int, url: str, media: list[str],
                   created: datetime | None, author: str = "") -> RawPost | None:
        if not key or key in self._seen or not text:
            return None
        self._seen.add(key)
        if not city:
            hit = infer_city(text)
            city = hit[0] if hit else ""
        return RawPost(
            platform="Telegram",
            author_handle=channel,
            author_name=author or channel,
            text=text[:1000],
            location=city,
            hashtags=[w.lstrip("#") for w in text.split() if w.startswith("#")],
            engagement={"likes": 0, "shares": forwards, "comments": 0, "views": views},
            url=url,
            media_urls=media,
            created_at=created,
        )

    def _note_flood(self, exc: Exception) -> bool:
        """Telegram answers over-use with FloodWaitError(seconds) — sometimes
        hours. Sleeping that out inline would stall the whole ingestion loop,
        so we park MTProto until the deadline and let the keyless preview path
        carry the seed channels in the meantime."""
        wait = getattr(exc, "seconds", None)
        if wait is None:
            return False
        self._mtproto_until = time.monotonic() + wait + 5
        log.warning("Telegram flood-wait %ss — MTProto paused, using previews", wait)
        return True

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        if (settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH
                and time.monotonic() >= self._mtproto_until):
            posts = await self._collect_mtproto(watch_terms)
            if posts:
                return posts
            # MTProto down (session expired, flood-wait) — previews still work.
        return await self._collect_preview()

    # ── keyless mode: t.me/s/<channel> public preview pages ──────────────

    def _preview_to_posts(self, html: str, channel: str, city: str) -> list[RawPost]:
        posts: list[RawPost] = []
        for post_id, block in _MSG_RE.findall(html):
            body = _TEXT_RE.search(block)
            if not body:
                continue  # media-only post, nothing to analyse
            author = _AUTHOR_RE.search(block)
            post = self._make_post(
                key=post_id,
                channel=channel,
                city=city,
                text=_strip_html(body.group(1)),
                views=_views(_VIEWS_RE.search(block).group(1) if _VIEWS_RE.search(block) else None),
                forwards=0,  # not exposed on preview pages
                url=f"https://t.me/{post_id}",
                media=_PHOTO_RE.findall(block),
                created=_iso(_TIME_RE.search(block).group(1) if _TIME_RE.search(block) else None),
                author=_strip_html(author.group(1)) if author else "",
            )
            if post:
                posts.append(post)
        return posts

    async def _collect_preview(self) -> list[RawPost]:
        posts: list[RawPost] = []
        channels = settings.TELEGRAM_CHANNELS
        if not channels:
            return posts
        batch = [channels[(self._cursor + i) % len(channels)]
                 for i in range(min(CHANNELS_PER_CYCLE, len(channels)))]
        self._cursor = (self._cursor + CHANNELS_PER_CYCLE) % len(channels)

        headers = {"User-Agent": PREVIEW_UA, "Accept-Language": "en-US,en;q=0.9"}
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                for channel, city in batch:
                    try:
                        r = await client.get(f"{PREVIEW_BASE}/{channel}", headers=headers)
                        r.raise_for_status()
                        posts.extend(self._preview_to_posts(r.text, channel, city))
                    except Exception as exc:
                        log.warning("Telegram preview failed for @%s: %s", channel, exc)
                    await asyncio.sleep(2)  # gap between channels inside one batch
        except Exception as exc:
            log.warning("Telegram preview collect failed: %s", exc)
        return posts

    async def disconnect(self) -> None:
        """Gracefully disconnect the MTProto client if connected."""
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    async def _connect(self):
        if self._client is not None:
            if hasattr(self._client, "is_connected") and self._client.is_connected():
                return self._client
            await self.disconnect()

        from telethon import TelegramClient          # lazy: optional dependency
        from telethon.sessions import StringSession

        session = (StringSession(settings.TELEGRAM_SESSION_STRING)
                   if settings.TELEGRAM_SESSION_STRING else str(SESSION_FILE))
        client = TelegramClient(session, settings.TELEGRAM_API_ID,
                                settings.TELEGRAM_API_HASH)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                raise RuntimeError(
                    "Telegram session not authorized — run "
                    "`python -m app.crawlers.telegram_login` once and put the "
                    "printed string in TELEGRAM_SESSION_STRING")
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
            raise
        self._client = client
        return client

    def _message_to_post(self, msg, channel: str, city: str) -> RawPost | None:
        text = (getattr(msg, "message", "") or "").strip()
        created = getattr(msg, "date", None)
        if created is not None:
            created = created.astimezone(timezone.utc).replace(tzinfo=None)
        return self._make_post(
            key=f"{channel}/{msg.id}",
            channel=channel,
            city=city,
            text=text,
            views=getattr(msg, "views", 0) or 0,
            forwards=getattr(msg, "forwards", 0) or 0,
            url=f"https://t.me/{channel}/{msg.id}",
            media=[],  # MTProto media needs a download round-trip; skip it
            created=created,
        )

    async def _collect_mtproto(self, watch_terms: list[str]) -> list[RawPost]:
        posts: list[RawPost] = []
        try:
            client = await self._connect()
        except Exception as exc:
            log.warning("Telegram MTProto connect failed (%s) — falling back to previews", exc)
            await self.disconnect()
            # Park MTProto for 1 hour on auth / connect failure so preview carries the load
            self._mtproto_until = time.monotonic() + 3600
            return posts

        # 1. seed channels — newest messages of each, geo-tagged from config
        for channel, city in settings.TELEGRAM_CHANNELS:
            try:
                async for msg in client.iter_messages(channel, limit=20):
                    post = self._message_to_post(msg, channel, city)
                    if post:
                        posts.append(post)
            except Exception as exc:
                log.warning("Telegram collect failed for @%s: %s", channel, exc)
                if self._note_flood(exc):
                    return posts  # keep what we have; the rest waits out the ban
            await asyncio.sleep(1)  # gap between channels inside one batch

        # There is deliberately no keyword-search step here. Telegram has no
        # public message-search API: messages.searchGlobal only searches chats
        # the *account has joined*, so on a monitoring account it returns
        # nothing and just burns rate limit. Coverage therefore comes from the
        # seed channel list, and finding new channels to add to it is a separate
        # offline job — telegram_discover.py, which uses contacts.Search (that
        # one does search all of Telegram, but for channels, not messages).
        return posts
