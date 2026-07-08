"""Continuous crawl loop — APScheduler drives every configured collector on a
fixed interval and hands results to the ingestion pipeline.

The tick itself can be fast (it feeds the simulator/UI); each live-platform
adapter additionally has a per-collector politeness gap (min_interval_seconds)
so real APIs are only queried in well-spaced batches, never hammered."""
import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import select

from app.config import settings
from app.crawlers import get_active_collectors
from app.database import session_scope
from app.models import WatchlistItem
from app.services.ingestion import ingest

log = logging.getLogger("sentinel.scheduler")
scheduler = AsyncIOScheduler()

_last_run: dict[str, float] = {}  # collector name -> monotonic time of last call


def _watch_terms() -> list[str]:
    with session_scope() as s:
        items = s.exec(
            select(WatchlistItem).where(
                WatchlistItem.active == True,  # noqa: E712
                WatchlistItem.kind.in_(["keyword", "hashtag"]),
            )
        ).all()
    return [i.value for i in items]


async def crawl_tick() -> None:
    terms = _watch_terms()
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
                      max_instances=1, coalesce=True)
    scheduler.start()
    log.info("Ingestion loop started (every %ss)", settings.INGEST_INTERVAL_SECONDS)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
