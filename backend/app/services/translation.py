"""English translations for stored posts, on demand and in the background.

Ingestion translates what it can as posts arrive, but that step is capped per
batch and skipped whenever the LLM budget is drained, so non-English posts
still reach screens and reports with no gloss. Everything here closes that gap
the same way: pick the posts that `needs_translation` says need one, translate
them in one batch, and store the result on the post so nobody pays for it twice.
"""
import asyncio
import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from sqlmodel import col, select

from app.database import session_scope
from app.models import Post
from app.services.groq_verifier import (TRANSLATE_MAX_PER_TICK, needs_translation,
                                        translate_enriched, translation_incomplete)

log = logging.getLogger("sentinel.translation")

#: How many untranslated posts the backfill reads before picking its batch.
#: Candidacy is decided by `needs_translation` on the text, which SQL cannot
#: express — so rows are scanned newest-first and filtered here.
BACKFILL_SCAN = 2000

#: Posts whose stored translation was found incomplete and re-translated in
#: this process. One attempt each: if the model still cannot do better, the
#: stored (partial) English is served rather than re-billing every page view.
_redone: set[str] = set()


async def _translate_rows(rows: list) -> dict[str, str]:
    """Translate (id, text, language) rows and store the results."""
    out: dict[str, str] = {}
    for start in range(0, len(rows), TRANSLATE_MAX_PER_TICK):
        batch = rows[start:start + TRANSLATE_MAX_PER_TICK]
        enriched = [{"language": r.language, "translation": ""} for r in batch]
        await translate_enriched([r.text for r in batch], enriched)
        done = {r.id: e["translation"] for r, e in zip(batch, enriched)
                if e.get("translation")}
        if not done:
            break   # the translator is not answering; do not hammer it
        out.update(done)
    if out:
        await asyncio.to_thread(_store, out)
    return out


def _store(translations: dict[str, str]) -> None:
    with session_scope() as s:
        for pid, text in translations.items():
            post = s.get(Post, pid)
            # Replace an existing translation only when it is one of the
            # incomplete ones — never a good one, whatever arrives later.
            if post and (not post.translation
                         or translation_incomplete(post.text, post.translation)):
                post.translation = text
                s.add(post)
        s.commit()


async def translate_posts(ids: Iterable[str]) -> dict[str, str]:
    """{post id: English translation} for the given posts, translating any
    that need one and do not have it yet. Posts that are already English are
    simply absent from the result."""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}

    def _load():
        with session_scope() as s:
            return s.exec(select(Post.id, Post.text, Post.language, Post.translation)
                          .where(col(Post.id).in_(ids))).all()

    rows = await asyncio.to_thread(_load)
    out = {r.id: r.translation for r in rows if r.translation}
    # Stored translations that are not really English (romanized Gujarati
    # copied through) are redone once, alongside the posts that have none.
    stale = [r for r in rows if r.translation and r.id not in _redone
             and translation_incomplete(r.text, r.translation)]
    _redone.update(r.id for r in stale)
    todo = [r for r in rows if not r.translation and r.text
            and needs_translation(r.text, {"language": r.language})] + stale
    if todo:
        out.update(await _translate_rows(todo))
    return out


def translate_posts_sync(ids: Iterable[str], timeout: float = 45) -> dict[str, str]:
    """`translate_posts` for synchronous callers (report generation).

    Runs on its own thread and event loop, so it works whether or not the
    caller is already inside one. Never raises: a report without translations
    is still a report.
    """
    ids = list(ids)
    if not ids:
        return {}
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, translate_posts(ids)).result(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("translation for %d post(s) failed: %s", len(ids), exc)
        return {}


async def backfill_missing(limit: int = TRANSLATE_MAX_PER_TICK) -> dict:
    """Translate the newest stored posts that still have no English gloss.

    Candidates are *not* selected as `language != 'English'`. That misses the
    posts this most needs to catch: the ones written in English apart from the
    Gujarati clause in the middle, which the detector labels English and an
    officer still cannot read. The same `needs_translation` rule the ingest
    pipeline uses decides here, so the two can never disagree.
    """
    def _load():
        with session_scope() as s:
            return s.exec(select(Post.id, Post.text, Post.language)
                          .where(Post.translation == "")
                          .order_by(col(Post.created_at).desc())
                          .limit(BACKFILL_SCAN)).all()

    rows = await asyncio.to_thread(_load)
    candidates = [r for r in rows if needs_translation(r.text, {"language": r.language})]
    if not candidates:
        return {"translated": 0, "remaining_candidates": 0}
    done = await _translate_rows(candidates[:limit])
    return {"translated": len(done),
            "remaining_candidates": max(0, len(candidates) - len(done))}
