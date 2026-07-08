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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from app.database import init_db, session_scope
from app.models import WatchlistItem
from app.routers import alerts, feed, network, reports, stats, trends, watchlist, ws
from app.services.ingestion import seed_if_empty
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sentinel")

from app.config import settings

DEFAULT_WATCHLIST = [
    ("keyword", "बच्चा चोर", "child-kidnapper rumor trigger phrase"),
    ("keyword", "sabak sikhana", "mobilization phrase (Hinglish)"),
    ("keyword", "ભેગા થાઓ", "gathering call (Gujarati)"),
    ("hashtag", "FinalWarning", "mobilization hashtag"),
    ("hashtag", "Boycott", "economic-exclusion campaigns"),
    ("account", "desh_sachai_*", "suspected bot network prefix"),
] + [
    ("location", city, f"geo watch: {city}") for city in settings.TARGET_CITIES
]


def _seed_watchlist() -> None:
    with session_scope() as s:
        if s.exec(select(WatchlistItem).limit(1)).first():
            return
        for kind, value, note in DEFAULT_WATCHLIST:
            s.add(WatchlistItem(kind=kind, value=value, note=note))
        s.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_watchlist()
    seed_if_empty()
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stats.router, prefix="/api", tags=["stats"])
app.include_router(feed.router, prefix="/api", tags=["feed"])
app.include_router(trends.router, prefix="/api", tags=["trends"])
app.include_router(network.router, prefix="/api", tags=["network"])
app.include_router(alerts.router, prefix="/api", tags=["alerts"])
app.include_router(reports.router, prefix="/api", tags=["reports"])
app.include_router(watchlist.router, prefix="/api", tags=["watchlist"])
app.include_router(ws.router, tags=["websocket"])


@app.get("/api/health")
def health() -> dict:
    from app.config import settings

    return {"status": "ok", "nlp_mode": settings.NLP_MODE, "simulation": settings.SIMULATION_ENABLED}
