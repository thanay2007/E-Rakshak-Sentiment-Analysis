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

    # YouTube Data API v3. The quota is the binding constraint, not politeness:
    # search.list costs 100 units against a 10,000/day project total, so the full
    # watchlist (~31 keyword/hashtag terms) would drain a day's budget in three
    # collects. The adapter therefore searches a rotating slice of the watchlist
    # per cycle and stops once the self-imposed budget is spent — every term
    # still gets covered, just spread across the day instead of all at once.
    # Budget math, so these stay tunable together: one searched (term, city) pair
    # costs ~112 units (100 search + 1 videos.list + 1 channels.list + ~10
    # commentThreads). At 2 pairs every 40 min that is 72 searches/day ≈ 8,064
    # units, leaving ~900 for analyst-triggered channel lookups. The watchlist
    # currently expands to ~88 pairs, so a full sweep takes a bit over a day —
    # the 10,000/day quota simply does not buy more than roughly one pass.
    # Raising TERMS_PER_CYCLE without lengthening the interval will overrun.
    YOUTUBE_API_KEY: str = ""
    YOUTUBE_DAILY_QUOTA: int = 9000   # headroom under the real 10,000/day cap
    YOUTUBE_TERMS_PER_CYCLE: int = 2
    YOUTUBE_MIN_INTERVAL_SECONDS: int = 2400

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

    # Telegram — official MTProto API credentials from my.telegram.org, plus a
    # session string generated once by `python -m app.crawlers.telegram_login`
    # (the login handshake needs a console; the ingest loop has none).
    # Without them the adapter still runs on t.me/s/<channel> public previews,
    # which cover the seed channels; neither mode has keyword search (Telegram
    # exposes no public message-search API).
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_SESSION_STRING: str = ""

    # Seed public channels (channel username, optional :City tag). A handle that
    # later goes dead just logs a warning and is skipped.
    # Every handle below was discovered through a directory search (not guessed)
    # and then verified against t.me/s/<name>: it exists, is public, is still
    # posting, and its content actually concerns Gujarat. Two failure modes make
    # that verification non-optional — many plausible handles simply don't exist,
    # and a dormant channel keeps serving its last 20 posts forever, which would
    # re-inject months-old content every cycle. Re-run
    # `python -m app.crawlers.telegram_discover` to refresh this list.
    #
    # Known dormant, do not re-add: gujaratsamacharofficial (Jul 2025),
    # network_news_gujarat (2020), YouthBarodian (2024), abpasmitatv (2022),
    # divyabhaskar (Feb 2026), zeenews (Apr 2026), TimesofIndia (2022).
    # Not public on t.me/s: vtvgujarati, news18gujarati, gstvnews,
    # sandesh_news_official, Gujarati_Daily_E_Paper.
    #
    # No :City tag on the statewide desks on purpose — they cover all four
    # cities, so per-post geo-tagging beats a blanket label.
    TELEGRAM_CHANNELS_RAW: list[str] = [
        # city desks
        "suratpolicesupporter:Surat",   # Surat police-adjacent, Gujarati
        "Ahmedabad_News:Ahmedabad",     # Ahmedabad news and updates
        "ahmedabadlivecommunity:Ahmedabad",
        # statewide Gujarati desks — no :City tag, geo-tagged per post
        "ddnews_gujarati",       # Doordarshan Gujarati — official public broadcaster
        "akilanews",             # Akila — Gujarati daily, Rajkot desk, statewide
        "khabargujarat",         # Khabar Gujarat News
        "loktej",                # Loktej — Hindi news out of Surat
        "manzilnewsgandhinagar2",  # Gujarati regional desk
        "aapgujaratofficial",    # party channel — political sentiment, Gujarati
        "gujaratieditorial",     # Gujarati editorial/opinion
        # national wires — Gujarat stories that break nationally first
        "ANINewsOfficial",
        "IndianExpress",
    ]

    @property
    def TELEGRAM_CHANNELS(self) -> list[tuple[str, str]]:
        out = []
        for entry in self.TELEGRAM_CHANNELS_RAW:
            source, _, city = entry.partition(":")
            if source.strip():
                out.append((source.strip().lstrip("@"), city.strip()))
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
