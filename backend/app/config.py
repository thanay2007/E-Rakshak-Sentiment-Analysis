"""Central configuration. Everything defaults to the zero-key demo mode."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
APP_DIR = Path(__file__).resolve().parent          # backend/app/
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _csv(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


def _seeded(name: str, default: str = "") -> list[tuple[str, str]]:
    """Parse a seed-source list: "id:City,id2:City2,id3" -> [(id, city), ...].
    The optional :City suffix geo-tags everything collected from that source."""
    out = []
    for entry in _csv(name, default):
        source, _, city = entry.partition(":")
        out.append((source.strip(), city.strip()))
    return [(s, c) for s, c in out if s]


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{BASE_DIR / 'sentinel.db'}"
    INGEST_INTERVAL_SECONDS: int = _int("INGEST_INTERVAL_SECONDS", 4)
    NLP_MODE: str = os.getenv("NLP_MODE", "full").strip().lower()  # full | lite
    ALERT_THRESHOLD: int = _int("ALERT_THRESHOLD", 65)
    CRITICAL_THRESHOLD: int = _int("CRITICAL_THRESHOLD", 74)
    SIMULATION_ENABLED: bool = _bool("SIMULATION_ENABLED", True)

    # Deployment scope — the cities this instance monitors (seed pages, default
    # watchlist locations and geo-tagging all key off this list).
    TARGET_CITIES: list[str] = _csv("TARGET_CITIES", "Surat,Ahmedabad,Vadodara,Rajkot")

    # Politeness floor for live-platform adapters: never hit the same API more
    # often than this, regardless of the ingestion tick. (The simulator ignores
    # it.) Rapid-fire queries against one endpoint look like abuse and get the
    # source blocked — batch, then wait.
    CRAWL_MIN_INTERVAL_SECONDS: int = _int("CRAWL_MIN_INTERVAL_SECONDS", 300)

    X_BEARER_TOKEN: str = os.getenv("X_BEARER_TOKEN", "").strip()
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "").strip()

    # Groq LLM second-opinion layer (services/groq_verifier.py). Free key from
    # console.groq.com — without it the layer simply stays off.
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    GROQ_VERIFY_MIN_SCORE: int = _int("GROQ_VERIFY_MIN_SCORE", 55)
    GROQ_MAX_PER_TICK: int = _int("GROQ_MAX_PER_TICK", 8)
    GROQ_TIMEOUT_SECONDS: int = _int("GROQ_TIMEOUT_SECONDS", 20)

    # Reddit official OAuth API (script app: client id + secret)
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "").strip()
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "sentinel-osint/1.0").strip()
    # Seed subreddits (the "seed URL" strategy): city subs are geo-tagged.
    REDDIT_SUBREDDITS: list[tuple[str, str]] = _seeded(
        "REDDIT_SUBREDDITS",
        "Surat:Surat,ahmedabad:Ahmedabad,Vadodara:Vadodara,rajkot:Rajkot,Gujarat",
    )

    # Facebook Graph API — a Page/System-User access token plus the seed pages
    # to monitor (page id or username, optional :City geo-tag).
    FB_ACCESS_TOKEN: str = os.getenv("FB_ACCESS_TOKEN", "").strip()
    FB_API_VERSION: str = os.getenv("FB_API_VERSION", "v21.0").strip()
    FB_PAGE_IDS: list[tuple[str, str]] = _seeded("FB_PAGE_IDS")

    # Instagram Graph API — token + the linked IG business-account id (needed
    # for business_discovery / hashtag search) + seed creator/business handles.
    IG_ACCESS_TOKEN: str = os.getenv("IG_ACCESS_TOKEN", "").strip()
    IG_BUSINESS_ACCOUNT_ID: str = os.getenv("IG_BUSINESS_ACCOUNT_ID", "").strip()
    IG_SEED_USERNAMES: list[tuple[str, str]] = _seeded("IG_SEED_USERNAMES")

    RSS_FEEDS: list[str] = _csv("RSS_FEEDS")

    REPORTS_DIR: Path = BASE_DIR / "reports"
    MODELS_DIR: Path = APP_DIR / "ml" / "models"
    DATA_DIR: Path = APP_DIR / "data"

    # How much simulated history to backfill on first boot (hours)
    SEED_HISTORY_HOURS: int = _int("SEED_HISTORY_HOURS", 48)


settings = Settings()
settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

THREAT_LABELS = ["Incitement to Violence", "Inflammatory", "Fake News", "Neutral"]
