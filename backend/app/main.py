"""SENTINEL backend entrypoint.

Boot sequence (all automatic, zero configuration):
  1. create tables
  2. seed default watchlist + simulated history if the DB is empty
  3. start the APScheduler ingestion loop (simulated stream by default,
     real platform adapters the moment API keys appear in .env)

Run:  uvicorn app.main:app --reload --port 8000  (from backend/)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from app.database import init_db, session_scope
from app.models import WatchlistItem
from app.routers import (
    admin, alerts, auth, faces, feed, investigate, network, reports, stats,
    trends, watchlist, ws,
)
from app.data.suspect_seed import seed_suspects_if_empty
from app.security.bootstrap import ensure_admin_exists
from app.security.deps import password_not_expired, require_admin
from app.security.ratelimit import default_rate_limit
from app.services.ingestion import seed_if_empty
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sentinel")

from app.config import settings
from app.ml.geo import _ALIASES as CITY_ALIASES

DEFAULT_WATCHLIST = [
    # Threat phrases across scripts (English / Hindi / Gujarati / romanized)
    ("keyword", "बच्चा चोर", "child-kidnapper rumor trigger phrase (Hindi)"),
    ("keyword", "bacha chor", "child-kidnapper rumor (Hinglish)"),
    ("keyword", "sabak sikhana", "mobilization phrase (Hinglish)"),
    ("keyword", "ભેગા થાઓ", "gathering call (Gujarati)"),
    ("keyword", "અફવા", "rumor (Gujarati)"),
    ("keyword", "afwa", "rumor (Gujlish/Hinglish)"),
    ("hashtag", "FinalWarning", "mobilization hashtag"),
    ("hashtag", "Boycott", "economic-exclusion campaigns"),
    ("account", "desh_sachai_*", "suspected bot network prefix"),
] + [
    # City names in every script so collectors pull posts in all five languages
    ("keyword", alias, "city watch (all scripts)")
    for city in settings.TARGET_CITIES
    for alias in CITY_ALIASES.get(city, [])
    if alias != city.lower()  # lowercase-English duplicate of the location entry below
] + [
    ("location", city, f"geo watch: {city}") for city in settings.TARGET_CITIES
]


def _seed_watchlist() -> None:
    from app.data.watchlist_packs import PACKS

    with session_scope() as s:
        if s.exec(select(WatchlistItem).limit(1)).first():
            return
        seen = set()
        for kind, value, note in DEFAULT_WATCHLIST:
            seen.add((kind, value.lower()))
            s.add(WatchlistItem(kind=kind, value=value, note=note))
        # every curated preset pack ships pre-applied on a fresh install
        for pack in PACKS.values():
            for kind, value, note, priority in pack["items"]:
                if (kind, value.lower()) in seen:
                    continue
                seen.add((kind, value.lower()))
                s.add(WatchlistItem(kind=kind, value=value, note=note,
                                    priority=priority, category=pack["title"]))
        s.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_admin_exists()
    _seed_watchlist()
    seed_if_empty()
    # after seed_if_empty: the demo suspect records bind their known handles to
    # accounts that actually exist in the corpus, so they need it populated
    seed_suspects_if_empty()
    start_scheduler()
    log.info("SENTINEL online")
    yield
    stop_scheduler()


app = FastAPI(
    title="SENTINEL — Social Media Threat & Sentiment Analyzer",
    description="Real-time multilingual OSINT threat-intelligence API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,     # explicit list; '*' is refused in config.py
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request, call_next):
    """Baseline response hardening.

    The API serves JSON and PDFs, never HTML, so a restrictive CSP costs
    nothing here and neutralises content-sniffing tricks against any endpoint
    that reflects attacker-supplied text.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy",
                                "default-src 'none'; frame-ancestors 'none'")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


# Every router is authenticated at the router level rather than per endpoint:
# a route added later is protected by default and has to be deliberately
# exempted, instead of being public until someone remembers a decorator.
# `password_not_expired` resolves `current_user`, so it authenticates and
# authorizes in one dependency.
_PROTECTED = [Depends(password_not_expired), Depends(default_rate_limit)]
_ADMIN_ONLY = [Depends(require_admin), Depends(default_rate_limit)]

app.include_router(auth.router, prefix="/api")            # its own guards inside
app.include_router(stats.router, prefix="/api", tags=["stats"], dependencies=_PROTECTED)
app.include_router(feed.router, prefix="/api", tags=["feed"], dependencies=_PROTECTED)
app.include_router(trends.router, prefix="/api", tags=["trends"], dependencies=_PROTECTED)
app.include_router(network.router, prefix="/api", tags=["network"], dependencies=_PROTECTED)
app.include_router(alerts.router, prefix="/api", tags=["alerts"], dependencies=_PROTECTED)
app.include_router(reports.router, prefix="/api", tags=["reports"], dependencies=_PROTECTED)
app.include_router(watchlist.router, prefix="/api", tags=["watchlist"], dependencies=_PROTECTED)
app.include_router(investigate.router, prefix="/api", tags=["investigate"], dependencies=_PROTECTED)
app.include_router(faces.router, prefix="/api", tags=["faces"], dependencies=_PROTECTED)
# The operations toolkit purges data, exports in bulk and spawns processes.
app.include_router(admin.router, prefix="/api", tags=["admin"], dependencies=_ADMIN_ONLY)
app.include_router(ws.router, tags=["websocket"])          # authenticates in-handshake


@app.get("/api/health")
def health() -> dict:
    """Unauthenticated liveness probe.

    Deliberately says nothing about configuration. The previous version
    advertised nlp_mode and whether the instance was running simulated or live
    data — free reconnaissance for anyone scanning the network. Operational
    detail now lives behind /api/admin/system.
    """
    return {"status": "ok"}
