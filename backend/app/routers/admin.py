"""Operations toolkit behind the Settings page — real actions, not just display.

Everything an analyst/operator needs at 2am without SSH access:
system + database health, live LLM-layer status (which Groq models are
drained), an on-demand crawl, translation backfill, language re-detection
(after detector upgrades), post CSV export, retention purge, and a classical-
model retrain launched as a subprocess with a pollable status.
"""
from __future__ import annotations

import csv
import io
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, func, select

from app.config import BASE_DIR, settings
from app.database import get_session, session_scope
from app.models import Alert, Post, Report, WatchlistItem

log = logging.getLogger("sentinel.admin")
router = APIRouter()

_STARTED_AT = time.time()


# ── system / health ─────────────────────────────────────────────────────────

@router.get("/admin/system")
def system_status(session: Session = Depends(get_session)) -> dict:
    from app.services.groq_client import status as groq_status
    from app.services.scheduler import scheduler

    from app.database import IS_SQLITE

    # Only a file-backed database has a size on disk; on Postgres the number
    # that matters lives on the server, not here.
    db_path = Path(settings.DATABASE_URL.replace("sqlite:///", "")) if IS_SQLITE else None
    counts = {
        "posts": session.exec(select(func.count()).select_from(Post)).one(),
        "alerts": session.exec(select(func.count()).select_from(Alert)).one(),
        "reports": session.exec(select(func.count()).select_from(Report)).one(),
        "watchlist": session.exec(select(func.count()).select_from(WatchlistItem)).one(),
    }
    newest = session.exec(select(func.max(Post.created_at))).one()
    oldest = session.exec(select(func.min(Post.created_at))).one()
    untranslated = session.exec(
        select(func.count()).select_from(Post)
        .where(Post.language != "English").where(Post.translation == "")
    ).one()
    return {
        "uptime_seconds": round(time.time() - _STARTED_AT),
        "nlp_mode": settings.NLP_MODE,
        "simulation": settings.SIMULATION_ENABLED,
        "ingest_interval_seconds": settings.INGEST_INTERVAL_SECONDS,
        "scheduler_running": scheduler.running,
        "database": {
            # Dialect only — the URL carries the Supabase password.
            "url": "sqlite (local file)" if IS_SQLITE else "postgres (hosted)",
            "size_mb": (round(db_path.stat().st_size / 1e6, 2)
                        if db_path and db_path.exists() else None),
            "counts": counts,
            "oldest_post": oldest.isoformat() if oldest else None,
            "newest_post": newest.isoformat() if newest else None,
            "untranslated_posts": untranslated,
        },
        "llm": groq_status(),
        "news": _news_status(),
    }


def _news_status() -> dict:
    from app.services.fact_check import gnews_status

    return {"google_news_rss": "unlimited (keyless)", "gnews": gnews_status()}


# ── LLM tools ───────────────────────────────────────────────────────────────

@router.post("/admin/test-llm")
async def test_llm() -> dict:
    """Ping the Groq fallback chain; reports which model answered and how fast."""
    from app.services import groq_client

    if not groq_client.enabled():
        return {"ok": False, "error": "GROQ_API_KEY not configured"}
    t0 = time.perf_counter()
    content, model = await groq_client.chat(
        [{"role": "user", "content": 'Reply with JSON {"pong": true}'}])
    ms = round((time.perf_counter() - t0) * 1000)
    if content is None:
        return {"ok": False, "error": "No model in the fallback chain responded",
                "status": groq_client.status()}
    return {"ok": True, "model": model, "latency_ms": ms}


@router.post("/admin/translate-missing")
async def translate_missing(limit: int = Query(40, ge=1, le=200)) -> dict:
    """Backfill English translations for stored non-English posts that never
    got one (e.g. because the LLM budget was drained at ingest time)."""
    from app.services.groq_verifier import translate_enriched

    with session_scope() as s:
        posts = s.exec(
            select(Post).where(Post.language != "English")
            .where(Post.translation == "")
            .order_by(col(Post.created_at).desc()).limit(limit)
        ).all()
        ids = [p.id for p in posts]
        texts = [p.text for p in posts]
        langs = [p.language for p in posts]
    if not posts:
        return {"translated": 0, "remaining_candidates": 0}
    enriched = [{"language": lang, "translation": ""} for lang in langs]
    n = await translate_enriched(texts, enriched)
    with session_scope() as s:
        for pid, e in zip(ids, enriched):
            if e.get("translation"):
                post = s.get(Post, pid)
                if post:
                    post.translation = e["translation"]
                    s.add(post)
        s.commit()
        remaining = s.exec(
            select(func.count()).select_from(Post)
            .where(Post.language != "English").where(Post.translation == "")
        ).one()
    return {"translated": n, "remaining_candidates": remaining}


@router.post("/admin/relabel-languages")
def relabel_languages(session: Session = Depends(get_session)) -> dict:
    """Re-run language detection over every stored post — applies detector
    upgrades (e.g. Filipino separation) to history. Posts whose language
    changes lose a stale translation so the backfill can redo it."""
    from app.ml.language import detect_language

    changed = 0
    for post in session.exec(select(Post)).all():
        lang, mixed = detect_language(post.text)
        if lang != post.language or mixed != post.code_mixed:
            if lang != post.language:
                post.translation = ""      # gloss was made under the wrong language
            post.language, post.code_mixed = lang, mixed
            session.add(post)
            changed += 1
    session.commit()
    return {"scanned": True, "relabeled": changed}


# ── data tools ──────────────────────────────────────────────────────────────

@router.get("/admin/export/posts.csv")
def export_posts(hours: int = Query(24, ge=1, le=24 * 90),
                 session: Session = Depends(get_session)) -> StreamingResponse:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["created_at", "platform", "author", "language", "threat_label",
                 "threat_score", "sentiment", "location", "text", "translation", "url"])
    for p in session.exec(select(Post).where(Post.created_at >= since)
                          .order_by(col(Post.created_at).desc())).all():
        wr.writerow([p.created_at.isoformat(), p.platform, p.author_handle,
                     p.language, p.threat_label, p.threat_score, p.sentiment_label,
                     p.location, p.text, p.translation, p.url])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename=posts_last_{hours}h.csv"})


@router.post("/admin/purge")
def purge_posts(days: int = Query(..., ge=1, le=365),
                session: Session = Depends(get_session)) -> dict:
    """Retention purge: deletes posts older than N days (their alerts survive
    as records). Deliberately requires an explicit day count."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    old = session.exec(select(Post).where(Post.created_at < cutoff)).all()
    for p in old:
        session.delete(p)
    session.commit()
    return {"deleted": len(old), "older_than_days": days}


# ── crawl / retrain jobs ────────────────────────────────────────────────────

@router.post("/admin/crawl-now")
async def crawl_now() -> dict:
    """Run one ingestion tick immediately (respects per-collector politeness
    gaps, so recently-queried live APIs are skipped, not hammered)."""
    from app.services.scheduler import crawl_tick

    with session_scope() as s:
        before = s.exec(select(func.count()).select_from(Post)).one()
    await crawl_tick()
    with session_scope() as s:
        after = s.exec(select(func.count()).select_from(Post)).one()
    return {"ok": True, "new_posts": after - before}


_retrain_proc: subprocess.Popen | None = None
_retrain_started: float | None = None


@router.post("/admin/retrain-baseline")
def retrain_baseline() -> dict:
    """Retrain the classical TF-IDF + LinearSVC sentiment model in a separate
    process (the corpus build is heavy — never done inside the API worker)."""
    global _retrain_proc, _retrain_started
    if _retrain_proc is not None and _retrain_proc.poll() is None:
        raise HTTPException(409, "A retrain is already running")
    _retrain_proc = subprocess.Popen(
        [sys.executable, "-m", "app.ml.train_baseline"], cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _retrain_started = time.time()
    log.info("baseline retrain launched (pid %s)", _retrain_proc.pid)
    return {"started": True, "pid": _retrain_proc.pid}


@router.get("/admin/retrain-baseline/status")
def retrain_status() -> dict:
    if _retrain_proc is None:
        return {"state": "idle"}
    rc = _retrain_proc.poll()
    elapsed = round(time.time() - (_retrain_started or time.time()))
    if rc is None:
        return {"state": "running", "elapsed_seconds": elapsed}
    if rc == 0:
        # freshly written model.joblib is picked up lazily; force a reload
        from app.ml import linear_model
        linear_model._model = None
        return {"state": "done", "elapsed_seconds": elapsed}
    return {"state": "failed", "exit_code": rc, "elapsed_seconds": elapsed}
