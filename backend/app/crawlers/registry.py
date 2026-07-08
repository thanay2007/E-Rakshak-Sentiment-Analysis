"""Collector registry — instantiates every adapter once and exposes the
configured ones. Adding a platform = one new file + one line here."""
from app.crawlers.base import Collector
from app.crawlers.facebook import FacebookCollector
from app.crawlers.instagram import InstagramCollector
from app.crawlers.reddit import RedditCollector
from app.crawlers.rss import RSSCollector
from app.crawlers.simulated import SimulatedCollector
from app.crawlers.twitter import XCollector
from app.crawlers.youtube import YouTubeCollector

_ALL: list[Collector] = [
    SimulatedCollector(),
    FacebookCollector(),
    InstagramCollector(),
    RedditCollector(),
    XCollector(),
    YouTubeCollector(),
    RSSCollector(),
]


def get_active_collectors() -> list[Collector]:
    return [c for c in _ALL if c.is_configured()]


def platform_status() -> list[dict]:
    return [{"name": c.name, "online": c.is_configured()} for c in _ALL]
