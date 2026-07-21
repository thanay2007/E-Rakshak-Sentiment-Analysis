"""Find Telegram channels covering the target cities, and verify them.

    cd backend && python -m app.crawlers.telegram_discover

Prints config-ready TELEGRAM_CHANNELS_RAW lines. Run it periodically: channels
go dormant, and a dormant channel keeps serving its last 20 posts forever.

Two discovery backends:
  * MTProto (contacts.Search) when TELEGRAM_API_ID/HASH/SESSION_STRING are set.
    This is Telegram's own index — by far the better source.
  * lyzem.com otherwise. Public and keyless, but it matches loosely: a query
    for 'rajkot police' returns Russian police forums and 'Android Police'.
    Hence the relevance scoring below.

Handles are never guessed. An earlier attempt generated ~1900 plausible
handles from city x language x suffix combinations and turned up 5 live
channels, most of them false friends — 'surat' is a Quran chapter and the
Uzbek word for picture, so bare-city handles are mostly not about Gujarat.
Every candidate here comes from a search index, then must survive verification.

Relevance is judged on title + description + a sample of actual posts, matching
target-city names in Latin, Gujarati and Devanagari. That is a *discovery*
filter for picking seed channels, deliberately not a per-post content filter —
posts are kept regardless of language and assessed after translation.
"""
import asyncio
import html as html_lib
import logging
import re
import unicodedata
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.crawlers.telegram import PREVIEW_UA, TelegramCollector, _TIME_RE, _strip_html

log = logging.getLogger("sentinel.crawlers")

TITLE_RE = re.compile(r'<div class="tgme_channel_info_header_title"[^>]*>(.*?)</div>', re.S)
DESC_RE = re.compile(r'<div class="tgme_channel_info_description"[^>]*>(.*?)</div>', re.S)
SUBS_RE = re.compile(r'<div class="tgme_channel_info_counter">.*?"counter_value">'
                     r'([^<]+)</span>\s*<span class="counter_type">subscribers', re.S)
HANDLE_RE = re.compile(r"t\.me/([A-Za-z0-9_]{5,32})")

MAX_AGE_DAYS = 45
SEARCH_PAGES = 6
# directory chrome, not content channels
JUNK = {"lyzembot", "mlyzembot", "lyzemcom", "editorpost_bot", "joinchat",
        "telegram", "share", "addstickers", "durov", "contact", "proxy", "socks"}

# City name in Latin / Gujarati / Devanagari — used both to build queries and
# to score whether a discovered channel is genuinely about that city.
CITY_TOKENS = {
    "Surat":     ["surat", "સુરત", "सूरत"],
    "Ahmedabad": ["ahmedabad", "amdavad", "અમદાવાદ", "अहमदाबाद"],
    "Vadodara":  ["vadodara", "baroda", "વડોદરા", "वडोदरा"],
    "Rajkot":    ["rajkot", "રાજકોટ", "राजकोट"],
}
GUJ_TOKENS = ["gujarat", "gujarati", "ગુજરાત", "ગુજરાતી", "गुजरात", "saurashtra", "સૌરાષ્ટ્ર"]
# Same trap as geo._CONFUSABLES: Suratgarh is in Rajasthan. Telegram's index
# returns a pile of Suratgarh coaching centres for a 'surat' query.
CONFUSABLES = ["suratgarh", "सूरतगढ़", "सूरतगढ"]
# contacts.Search is unfiltered, so city queries also return escort spam,
# stock-tip channels and trade/wholesale groups. None are civic signal.
SPAM_TOKENS = ["girl", "call boy", "escort", "dating", "hot ", "sexy", "18+",
               "sureshot", "jackpot", "betting", "profit", "intraday", "nifty",
               "banknifty", "loot", "deal", "saree", "fabric", "wholesale",
               "karigar", "job vacancy", "matrimony"]
# words for "news" across the registers this deployment sees
NEWS_WORDS = ["news", "samachar", "khabar", "સમાચાર", "ખબર", "समाचार", "खबर",
              "live", "update", "police", "epaper"]
GUJ_RANGE = range(0x0A80, 0x0B00)  # Gujarati Unicode block


def _queries() -> dict[str, list[str]]:
    """city -> search queries, one per (city spelling x news word) plus bare."""
    out: dict[str, list[str]] = {}
    for city in settings.TARGET_CITIES:
        toks = CITY_TOKENS.get(city, [city.lower()])
        qs = list(toks)
        for t in toks:
            qs.extend(f"{t} {w}" for w in NEWS_WORDS)
        out[city] = qs
    out[""] = [f"{g} {w}" for g in GUJ_TOKENS[:4] for w in NEWS_WORDS[:6]]
    return out


async def _lyzem(client: httpx.AsyncClient, sem, q: str, city: str, found: dict) -> None:
    for page in range(1, SEARCH_PAGES + 1):
        async with sem:
            params = {"f": "channels", "q": q}
            if page > 1:
                params["p"] = page
            try:
                r = await client.get("https://lyzem.com/search", params=params)
                if r.status_code != 200:
                    return
                hits = {h for h in HANDLE_RE.findall(r.text) if h.lower() not in JUNK}
            except Exception:
                return
            if not hits:
                return
            for h in hits:
                found.setdefault(h.lower(), (h, set()))[1].add(city)
        await asyncio.sleep(0.4)  # keep the free directory happy


async def _mtproto(found: dict) -> bool:
    """Telegram's own channel index. Returns False if unavailable."""
    if not (settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH):
        return False
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.functions.contacts import SearchRequest
    except ImportError:
        return False
    try:
        session = (StringSession(settings.TELEGRAM_SESSION_STRING)
                   if settings.TELEGRAM_SESSION_STRING else "telegram_session")
        async with TelegramClient(session, settings.TELEGRAM_API_ID,
                                  settings.TELEGRAM_API_HASH) as client:
            for city, queries in _queries().items():
                for q in queries:
                    try:
                        res = await client(SearchRequest(q=q, limit=50))
                    except Exception as exc:
                        log.warning("Telegram search failed for '%s': %s", q, exc)
                        continue
                    for chat in res.chats:
                        u = getattr(chat, "username", None)
                        if u:
                            found.setdefault(u.lower(), (u, set()))[1].add(city)
                    await asyncio.sleep(1)
        return True
    except Exception as exc:
        log.warning("Telegram MTProto discovery unavailable: %s", exc)
        return False


async def _verify(client: httpx.AsyncClient, sem, handle: str, cities: set,
                  out: list) -> None:
    """A candidate only survives if it is public, still posting, and its own
    words are about Gujarat."""
    async with sem:
        try:
            r = await client.get(f"https://t.me/s/{handle}",
                                 headers={"User-Agent": PREVIEW_UA})
        except Exception:
            return
        if r.status_code != 200 or not r.text.count("data-post"):
            return
        page = r.text

    newest = None
    for d in _TIME_RE.findall(page):
        try:
            dt = datetime.fromisoformat(d).astimezone(timezone.utc).replace(tzinfo=None)
            newest = dt if newest is None or dt > newest else newest
        except ValueError:
            pass
    if newest is None or (datetime.utcnow() - newest).days > MAX_AGE_DAYS:
        return

    tm, dm, sm = TITLE_RE.search(page), DESC_RE.search(page), SUBS_RE.search(page)
    title = html_lib.unescape(_strip_html(tm.group(1))) if tm else ""
    desc = html_lib.unescape(_strip_html(dm.group(1))) if dm else ""
    sample = " ".join(p.text for p in TelegramCollector()._preview_to_posts(page, handle, ""))
    # NFC matters here for the same reason it does in geo._norm — ढ़ has two
    # encodings, so 'सूरतगढ़' in a channel title may not equal ours literally.
    # The handle goes in the blob too: 'Ahmedabad_girls22' titles itself
    # innocuously and is only identifiable from the username.
    blob = unicodedata.normalize("NFC", f"{handle} {title} {desc} {sample}").lower()

    if any(s in blob for s in SPAM_TOKENS):
        return  # escort / stock-tip / wholesale channel, not civic signal
    for bad in CONFUSABLES:
        blob = blob.replace(bad, " ")

    matched = [c for c, toks in CITY_TOKENS.items() if any(t in blob for t in toks)]
    guj = any(t in blob for t in GUJ_TOKENS)
    guj_pct = round(100 * sum(1 for ch in sample if ord(ch) in GUJ_RANGE) / max(len(sample), 1))
    if not (matched or guj or guj_pct > 15):
        return  # a false friend: matched the query text but isn't about Gujarat
    out.append({"handle": handle, "cities": matched, "gujarat": guj,
                "guj_pct": guj_pct, "newest": newest, "title": title,
                "desc": desc[:80], "subs": sm.group(1) if sm else "?",
                "hinted": sorted(c for c in cities if c)})


async def main() -> None:
    found: dict[str, tuple[str, set]] = {}
    if await _mtproto(found):
        print(f"discovery: MTProto (contacts.Search) -> {len(found)} handles")
    else:
        print("discovery: lyzem (set TELEGRAM_API_ID/HASH for Telegram's own index)")
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(headers={"User-Agent": PREVIEW_UA},
                                     follow_redirects=True, timeout=25) as client:
            await asyncio.gather(*(_lyzem(client, sem, q, city, found)
                                   for city, qs in _queries().items() for q in qs))
        print(f"  -> {len(found)} handles")

    out: list[dict] = []
    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(follow_redirects=True, timeout=25) as client:
        await asyncio.gather(*(_verify(client, sem, h, c, out)
                               for h, c in found.values()))
    out.sort(key=lambda r: (-len(r["cities"]), -r["guj_pct"]))

    print(f"\n{len(out)} verified: public, posted within {MAX_AGE_DAYS}d, Gujarat-relevant\n")
    print(f"{'handle':32s} {'cities':24s} {'guj%':>5s} {'newest':12s} {'subs':>8s}  title")
    print("-" * 110)
    for r in out:
        print(f"{r['handle']:32s} {','.join(r['cities']) or '-':24s} {r['guj_pct']:4d}% "
              f"{r['newest'].date()!s:12s} {r['subs']:>8s}  {r['title'][:30]}")

    print("\n# TELEGRAM_CHANNELS_RAW candidates:")
    for r in out:
        tag = f":{r['cities'][0]}" if len(r["cities"]) == 1 else ""
        print(f'    "{r["handle"]}{tag}",  # {r["title"][:44]}')


if __name__ == "__main__":
    asyncio.run(main())
