"""Collector registry — one entry per *logical platform*, not per adapter.

A platform can have more than one way in: an official API and a keyless or
scraped fallback. They are listed in preference order and exactly one runs —
the first that is configured. Dropping an official key into .env therefore
upgrades the source in place, with no duplicate ingestion and nothing else to
change; pulling the key back out falls straight back to the keyless path.

Reddit and Telegram handle that switch internally (OAuth vs Atom feeds, MTProto
vs t.me previews), so they appear once. X needs it here, because the official
v2 adapter and the twikit session-cookie adapter are separate classes that both
emit platform="X" — running both would ingest every post twice.

Adding a platform = one new file + one line here.
"""
from app.crawlers.base import Collector
from app.crawlers.facebook import FacebookCollector
from app.crawlers.instagram import InstagramCollector
from app.crawlers.reddit import RedditCollector
from app.crawlers.simulated import SimulatedCollector
from app.crawlers.telegram import TelegramCollector
from app.crawlers.twikit_x import TwikitXCollector
from app.crawlers.twitter import XCollector
from app.crawlers.youtube import YouTubeCollector

# (platform name, adapters in preference order — official API first)
_PLATFORMS: list[tuple[str, list[Collector]]] = [
    ("X", [XCollector(), TwikitXCollector()]),
    ("Reddit", [RedditCollector()]),
    ("Telegram", [TelegramCollector()]),
    ("YouTube", [YouTubeCollector()]),
    ("Facebook", [FacebookCollector()]),
    ("Instagram", [InstagramCollector()]),
]

# Not a real platform — the demo generator. It only appears at all when
# SIMULATION_ENABLED, so a live deployment reports genuine sources only.
_SIMULATED = SimulatedCollector()


def _preferred(adapters: list[Collector]) -> Collector | None:
    """The first configured adapter for a platform, or None if it's offline."""
    for c in adapters:
        if c.is_configured():
            return c
    return None


def get_active_collectors() -> list[Collector]:
    collectors = [c for _, adapters in _PLATFORMS if (c := _preferred(adapters))]
    if _SIMULATED.is_configured():
        collectors.append(_SIMULATED)
    return collectors


def platform_status() -> list[dict]:
    """One row per platform. `adapter` names the route actually in use, so an
    analyst can tell official-API traffic from the keyless fallback."""
    rows = []
    for name, adapters in _PLATFORMS:
        c = _preferred(adapters)
        rows.append({"name": name, "online": c is not None,
                     "adapter": c.name if c else ""})
    if _SIMULATED.is_configured():
        rows.append({"name": _SIMULATED.name, "online": True,
                     "adapter": _SIMULATED.name})
    return rows
