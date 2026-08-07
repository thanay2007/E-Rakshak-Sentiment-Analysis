"""Continuous crawl loop — APScheduler drives every configured collector on a
fixed interval and hands results to the ingestion pipeline.

The tick itself can be fast (it feeds the simulator/UI); each live-platform
adapter additionally has a per-collector politeness gap (min_interval_seconds)
so real APIs are only queried in well-spaced batches, never hammered."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.crawlers import get_active_collectors
from app.security.context import SYSTEM, reset_actor, set_actor
from app.services.ingestion import ingest
from app.services.watch_targets import invalidate as invalidate_watch_cache
from app.services.watch_targets import watch_terms as _watch_terms

log = logging.getLogger("sentinel.scheduler")
scheduler = AsyncIOScheduler()

_last_run: dict[str, float] = {}  # collector name -> monotonic time of last call

#: Re-exported under its original name: the watchlist router calls this on
#: every edit, and the caching itself now lives in watch_targets, where a
#: crawler can reach it without importing the scheduler.
invalidate_watch_terms = invalidate_watch_cache


async def crawl_tick() -> None:
    # Tag everything this tick writes as system activity. Without it a
    # background ingest inherits whatever actor happened to be set on the task
    # that triggered it — an officer's name against work they did not do.
    # /admin/crawl-now runs this same function, so the reset in `finally`
    # matters: it must not leave the request context stamped as `system`.
    token = set_actor(SYSTEM)
    try:
        await _crawl_tick_inner()
    finally:
        reset_actor(token)


async def _crawl_tick_inner() -> None:
    # Off the loop: this is a synchronous database call, and the scheduler
    # shares its event loop with every request the API is serving. Inline, it
    # stalled all of them for a round trip several times a minute.
    terms = await asyncio.to_thread(_watch_terms)
    raws = []
    now = time.monotonic()
    for collector in get_active_collectors():
        last = _last_run.get(collector.name)
        if last is not None and now - last < collector.min_interval_seconds:
            continue  # politeness gap not elapsed yet
        _last_run[collector.name] = now
        try:
            raws.extend(await collector.collect(terms))
        except Exception as exc:  # adapters shouldn't raise, but never stall the loop
            log.warning("%s collector failed: %s", collector.name, exc)
    if raws:
        n = await ingest(raws)
        if n:
            log.debug("Ingested %d new posts", n)


def start_scheduler() -> None:
    scheduler.add_job(crawl_tick, "interval",
                      seconds=settings.INGEST_INTERVAL_SECONDS,
                      next_run_time=datetime.now(timezone.utc) + timedelta(
                          seconds=max(0, settings.SCHEDULER_START_DELAY_SECONDS)),
                      max_instances=1, coalesce=True)
    scheduler.start()
    log.info("Ingestion loop started (every %ss, first run in %ss)",
             settings.INGEST_INTERVAL_SECONDS,
             settings.SCHEDULER_START_DELAY_SECONDS)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
