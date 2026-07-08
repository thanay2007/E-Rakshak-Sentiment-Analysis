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

    @abstractmethod
    def is_configured(self) -> bool:
        """True when this adapter has what it needs (API keys, feeds, ...)."""

    @abstractmethod
    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        """Fetch new items matching the watchlist terms."""
