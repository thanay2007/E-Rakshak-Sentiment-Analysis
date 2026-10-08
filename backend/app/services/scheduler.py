"""Continuous crawl loop — APScheduler drives every configured collector on a
completion-based interval and hands results to the ingestion pipeline.

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
    due = []
    for collector in get_active_collectors():
        last = _last_run.get(collector.name)
        if last is not None and now - last < collector.min_interval_seconds:
            continue
        _last_run[collector.name] = now
        due.append(collector)

    async def collect_one(collector):
        try:
            return await asyncio.wait_for(collector.collect(terms),
                                          timeout=collector.timeout_seconds)
        except asyncio.TimeoutError:
            log.warning("%s collector timed out after %ds — skipping it this tick",
                        collector.name, collector.timeout_seconds)
        except Exception as exc:
            log.warning("%s collector failed: %s", collector.name, exc)
        return []

    # A slow login or browser must not hold up starting the other sources.
    # Each source keeps its own timeout and politeness gap; result order stays
    # deterministic even when requests finish in a different order.
    batches = await asyncio.gather(*(collect_one(collector) for collector in due))
    raws = [post for batch in batches for post in batch]
    if raws:
        n = await ingest(raws)
        if n:
            log.debug("Ingested %d new posts", n)

    # Rebuild the dashboard's two expensive windows off the loop, so the first
    # analyst to open it is served from a warm cache instead of waiting out a
    # multi-second scan: the emerging-rumour queue (every post's engagement and
    # fact-check payload) and the fake-PR campaign count (a shingle overlap
    # plus a bot score per author).
    from app.osint.pr_analysis import prime_count_cache
    from app.services.emerging import prime_cache

    for label, prime in (("emerging", prime_cache),
                         ("fake-PR", prime_count_cache)):
        try:
            await asyncio.to_thread(prime)
        except Exception as exc:                  # noqa: BLE001 — never stall ingestion
            log.debug("%s cache prime skipped: %s", label, exc)


def _schedule_next(delay: float) -> None:
    scheduler.add_job(_scheduled_crawl, "date", id="crawl_tick", name="crawl_tick",
                      run_date=datetime.now(timezone.utc) + timedelta(seconds=max(0, delay)),
                      replace_existing=True, misfire_grace_time=15)


async def _scheduled_crawl() -> None:
    try:
        await crawl_tick()
    except Exception:
        log.exception("Collection cycle failed; the next cycle will retry")
    finally:
        # Schedule from completion rather than repeatedly queuing a long job.
        # A shutdown must not bring the scheduler back to life.
        if scheduler.running:
            _schedule_next(settings.INGEST_INTERVAL_SECONDS)


def start_scheduler() -> None:
    _schedule_next(settings.SCHEDULER_START_DELAY_SECONDS)
    scheduler.start()
    log.info("Ingestion loop started (pause %ss after each cycle, first run in %ss)",
             settings.INGEST_INTERVAL_SECONDS,
             settings.SCHEDULER_START_DELAY_SECONDS)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
