"""Simulated ingestion — the zero-key default that makes `git clone → run`
show a live multilingual stream immediately."""
from app.config import settings
from app.crawlers.base import Collector
from app.data.simulator import get_simulator
from app.schemas import RawPost


class SimulatedCollector(Collector):
    name = "Simulated Stream"

    def is_configured(self) -> bool:
        return settings.SIMULATION_ENABLED

    async def collect(self, watch_terms: list[str]) -> list[RawPost]:
        return get_simulator().stream_tick()
