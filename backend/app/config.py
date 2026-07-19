"""Central configuration. Everything defaults to the zero-key demo mode."""
from pathlib import Path
from typing import List, Tuple

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
APP_DIR = Path(__file__).resolve().parent          # backend/app/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'sentinel.db'}"
    INGEST_INTERVAL_SECONDS: int = 4
    NLP_MODE: str = "full"  # full | lite
    ALERT_THRESHOLD: int = 65
    CRITICAL_THRESHOLD: int = 74
    SIMULATION_ENABLED: bool = True

    # Deployment scope — the cities this instance monitors (seed pages, default
    # watchlist locations and geo-tagging all key off this list).
    TARGET_CITIES: list[str] = ["Surat", "Ahmedabad", "Vadodara", "Rajkot"]

    # Politeness floor for live-platform adapters: never hit the same API more
    # often than this, regardless of the ingestion tick. (The simulator ignores
    # it.) Rapid-fire queries against one endpoint look like abuse and get the
    # source blocked — batch, then wait.
    CRAWL_MIN_INTERVAL_SECONDS: int = 300

    X_BEARER_TOKEN: str = ""
    YOUTUBE_API_KEY: str = ""

    # X via twikit (unofficial, key-free) — credentials of a real X account
    # (use a dedicated burner). Activates the "X (twikit)" adapter when
    # username + password are set; cookies persist in backend/x_cookies.json.
    X_USERNAME: str = ""
    X_EMAIL: str = ""
    X_PASSWORD: str = ""
    # Preferred twikit auth: session cookies from a browser logged into x.com
    # (Cloudflare blocks the password-login endpoint for Python clients).
    X_AUTH_TOKEN: str = ""
    X_CT0: str = ""

    # Groq LLM second-opinion layer (services/groq_verifier.py). Free key from
    # console.groq.com — without it the layer simply stays off.
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    # Cheaper model for high-volume background work (translation) so the big
    # model's daily token budget stays available for analyst-triggered work.
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"
    # Groq rate limits are PER MODEL — when one model's daily budget drains,
    # the next in this chain still has quota. Every LLM call walks this list.
    GROQ_FALLBACK_MODELS: list[str] = [
        "llama-3.1-8b-instant",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.6-27b",
    ]
    GROQ_VERIFY_MIN_SCORE: int = 55
    GROQ_MAX_PER_TICK: int = 8
    GROQ_TIMEOUT_SECONDS: int = 20

    # GNews (gnews.io) — richer news corroboration for analyst-triggered
    # fact-checks and evidence dossiers. Free tier: 100 requests/day, so the
    # background ingest loop never touches it (it stays on Google News RSS).
    GNEWS_API_KEY: str = ""
    GNEWS_DAILY_BUDGET: int = 80  # self-imposed cap under the 100/day limit

    # Twilio WhatsApp Alerts
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_TO: str = ""
    TWILIO_WHATSAPP_FROM: str = "+14155238886"

    # Reddit official OAuth API (script app: client id + secret)
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "sentinel-osint/1.0"
    
    # Seed subreddits (the "seed URL" strategy): city subs are geo-tagged.
    REDDIT_SUBREDDITS_RAW: list[str] = ["Surat:Surat", "ahmedabad:Ahmedabad", "Vadodara:Vadodara", "rajkot:Rajkot", "Gujarat"]

    @property
    def REDDIT_SUBREDDITS(self) -> list[tuple[str, str]]:
        out = []
        for entry in self.REDDIT_SUBREDDITS_RAW:
            source, _, city = entry.partition(":")
            if source.strip():
                out.append((source.strip(), city.strip()))
        return out

    # Facebook Graph API — a Page/System-User access token plus the seed pages
    # to monitor (page id or username, optional :City geo-tag).
    FB_ACCESS_TOKEN: str = ""
    FB_API_VERSION: str = "v21.0"
    FB_PAGE_IDS_RAW: list[str] = []

    @property
    def FB_PAGE_IDS(self) -> list[tuple[str, str]]:
        out = []
        for entry in self.FB_PAGE_IDS_RAW:
            source, _, city = entry.partition(":")
            if source.strip():
                out.append((source.strip(), city.strip()))
        return out

    # Instagram Graph API — token + the linked IG business-account id (needed
    # for business_discovery / hashtag search) + seed creator/business handles.
    IG_ACCESS_TOKEN: str = ""
    IG_BUSINESS_ACCOUNT_ID: str = ""
    IG_SEED_USERNAMES_RAW: list[str] = []

    @property
    def IG_SEED_USERNAMES(self) -> list[tuple[str, str]]:
        out = []
        for entry in self.IG_SEED_USERNAMES_RAW:
            source, _, city = entry.partition(":")
            if source.strip():
                out.append((source.strip(), city.strip()))
        return out

    RSS_FEEDS: list[str] = []

    REPORTS_DIR: Path = BASE_DIR / "reports"
    MODELS_DIR: Path = APP_DIR / "ml" / "models"
    DATA_DIR: Path = APP_DIR / "data"

    # How much simulated history to backfill on first boot (hours)
    SEED_HISTORY_HOURS: int = 48


settings = Settings()
settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

THREAT_LABELS = ["Incitement to Violence", "Inflammatory", "Fake News", "Neutral"]
