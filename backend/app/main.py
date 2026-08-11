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

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import select

from app.database import init_db, session_scope
from app.models import WatchlistItem
from app.routers import (
    admin, alerts, assistant, auth, faces, feed, investigate, media, network,
    reports, stats, trends, voice, watchlist, ws,
)
from app.data.suspect_seed import seed_suspects_if_empty
from app.security.bootstrap import ensure_admin_exists
from app.security.deps import password_not_expired, require_admin
from app.security.ratelimit import default_rate_limit
from app.services.assistant.sandbox import ensure_views as ensure_assistant_views
from app.services.ingestion import seed_if_empty
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sentinel")

# Silence noisy third-party loggers
logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)
for _lib in ("instagrapi", "public_request", "private_request", "instagrapi.mixins.user",
            "instagrapi.mixins.private", "instagrapi.mixins.challenge", "instagrapi.mixins.auth"):
    _l = logging.getLogger(_lib)
    _l.setLevel(logging.CRITICAL)
    _l.propagate = False

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
    # After init_db, because these are views over tables Alembic owns. They are
    # the assistant's read-only window — see services/assistant/sandbox.py for
    # why the projection is part of the security boundary rather than a
    # migration. Failure is logged there and leaves the SQL tool unavailable.
    ensure_assistant_views()
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
    # Clean up any active crawler background sessions (Telethon, etc.)
    from app.crawlers.registry import get_collector
    tg = get_collector("Telegram")
    if tg and hasattr(tg, "disconnect"):
        try:
            await tg.disconnect()
        except Exception:
            pass


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

# Rejects a forged Host header before routing. Without it a request claiming
# `Host: evil.example` is served normally, and anything that echoes the host
# into a link — a password flow, an emailed report URL — points at the attacker.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Refuse oversized bodies on the declared length, before reading them.

    Only the image/face tools legitimately send large bodies. Without a ceiling
    a single request can pin the worker's memory for as long as it takes to
    stream — a cheap denial of service against a system that is supposed to be
    watching for one.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.MAX_REQUEST_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": "Request body too large."})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
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
    # This API needs none of the powerful browser features, and a response that
    # says so cannot be used to reach them from an embedded context.
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if settings.ENABLE_HSTS:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """Log the detail, return none of it.

    A stack trace or driver message in a 500 body is free reconnaissance —
    table names, file paths, library versions. The full exception goes to the
    server log where the operator can read it and the caller cannot.
    """
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. It has been logged."})


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
# Post media, fetched server-side so the browser never talks to a platform CDN
# (and the CDN never learns which post an officer opened) — see routers/media.py.
app.include_router(media.router, prefix="/api", tags=["media"], dependencies=_PROTECTED)
# The voice assistant. Authenticated like everything else and read-only by
# construction — see routers/assistant.py for what it is and is not allowed to
# reach, which is the whole security story for a feature driven by a hot mic.
app.include_router(assistant.router, prefix="/api", tags=["assistant"], dependencies=_PROTECTED)
# The operations toolkit purges data, exports in bulk and spawns processes.
app.include_router(admin.router, prefix="/api", tags=["admin"], dependencies=_ADMIN_ONLY)
app.include_router(ws.router, tags=["websocket"])          # authenticates in-handshake
# The real-time voice channel. Authenticates in-handshake like /ws/live, and
# runs every spoken question through the same assistant guard the typed
# endpoint uses — voice is a transport, not a wider permission.
app.include_router(voice.router, tags=["voice"])


@app.get("/api/health")
def health() -> dict:
    """Unauthenticated liveness probe.

    Deliberately says nothing about configuration. The previous version
    advertised nlp_mode and whether the instance was running simulated or live
    data — free reconnaissance for anyone scanning the network. Operational
    detail now lives behind /api/admin/system.
    """
    return {"status": "ok"}
