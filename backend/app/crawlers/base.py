"""Collector interface. Every platform adapter implements this; the scheduler
treats them uniformly. Adapters must NEVER raise out of collect() — log and
return [] so one dead platform can't stall the ingestion loop.

Live adapters declare min_interval_seconds > 0: the scheduler will not call
them again before that many seconds have passed, however fast the ingestion
tick runs. Batch a source's queries in one collect() call, then leave the gap —
hammering one endpoint gets the account/IP blocked."""
from abc import ABC, abstractmethod

from app.schemas import RawPost


class Collector(ABC):
    name: str = "base"
    # 0 = run every tick (simulator); live adapters set a real politeness gap.
    min_interval_seconds: int = 0
    # How long the scheduler waits for one collect() before giving up on it and
    # moving to the next platform. Adapters are called one after another in a
    # single tick, so an adapter that never returns does not just lose its own
    # platform — it starves every platform below it in the list and every tick
    # that follows, because the tick never finishes. Instagram's private-API
    # client has done exactly that (a refused login that blocks instead of
    # raising), taking Facebook and the whole loop down with it while every
    # source still reported itself online. Raise it for an adapter that is
    # legitimately slow rather than stuck; the browser-driven ones are.
    timeout_seconds: int = 120

    @abstractmethod
    def is_configured(self) -> bool:
        """True when this adapter has what it needs (API keys, feeds, ...)."""

    @abstractmethod
    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        """Fetch new items matching the watchlist terms."""

    def status_detail(self) -> str:
        """Why this adapter is not usable right now, in words an operator can
        act on — empty when there is nothing to say.

        `is_configured()` answers yes/no and that is all the scheduler needs,
        but "Instagram: offline" with no reason is indistinguishable from
        "Instagram: never set up", and the two have completely different
        fixes. Adapters that can fail *after* being configured (an expired
        session, a revoked token) should say so here.
        """
        return ""
