"""Central configuration. Everything defaults to the zero-key demo mode."""
from pathlib import Path
from typing import List, Tuple

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
APP_DIR = Path(__file__).resolve().parent          # backend/app/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    # Where every post, alert, report, watchlist entry and audit row is kept.
    #
    # SQLite by default (zero-setup demo). Point this at Supabase — or any
    # Postgres — to make the corpus durable and shared instead of a file on one
    # laptop; database.py detects the dialect and applies the right migrations
    # and append-only triggers either way. Supabase gives you the string under
    # Project Settings → Database → Connection string; use the *session pooler*
    # (port 5432) or transaction pooler (6543) URI and rewrite the scheme:
    #
    #   DATABASE_URL=postgresql+psycopg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
    #
    # Nothing in this application deletes history on its own — retention is an
    # explicit admin action — so a Postgres target simply accumulates the full
    # record rather than only what the current process has seen.
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'sentinel.db'}"
    # Connection recycling for hosted Postgres. Supabase's pooler drops idle
    # connections; without pre-ping the first query after an idle period fails
    # with a stale-connection error instead of transparently reconnecting.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_ECHO: bool = False

    # Run `alembic upgrade head` at boot. On by default so a fresh clone and a
    # fresh Supabase project both just work. Turn it off where migrations are a
    # reviewed, deliberate step run ahead of the deploy — with more than one
    # worker you want exactly one process applying them, not a race.
    AUTO_MIGRATE: bool = True

    INGEST_INTERVAL_SECONDS: int = 4
    # Delay the first background crawl after API startup. Live collectors and
    # full NLP can be expensive; the login screen and dashboard should become
    # reachable before that work starts.
    SCHEDULER_START_DELAY_SECONDS: int = 60
    # ── security ────────────────────────────────────────────────────────────
    # Signing key for session tokens. MUST be set in production; when empty the
    # process generates a random key at boot (sessions die on every restart and
    # multi-worker deployments break outright — loud by design).
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    SECRET_KEY: str = ""
    ACCESS_TOKEN_TTL_MINUTES: int = 8 * 60      # one shift

    # Browser origins allowed to call the API. A wildcard is rejected at startup:
    # this API serves criminal records, so "any website may drive it with the
    # officer's credentials" is never an acceptable configuration.
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Host names this API will answer to. Anything else gets a 400 before the
    # request reaches a route: a forged Host header otherwise poisons absolute
    # URLs in generated links and password-style flows. "*" is allowed only
    # while SIMULATION_ENABLED (the demo posture) — see the check below.
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "[::1]", "testserver"]

    # Hard ceiling on a request body, enforced before parsing. Uploads to the
    # image/face tools are the only large bodies this API legitimately sees.
    MAX_REQUEST_BYTES: int = 25 * 1024 * 1024

    # Emit HSTS. Off by default because it is actively harmful over plain HTTP
    # on localhost (the browser pins the host to https for a year). Turn it on
    # the moment this sits behind TLS.
    ENABLE_HSTS: bool = False

    # Brute-force lockout on the login endpoint.
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Provisioned console administrator (security/bootstrap.py). Created if it
    # does not exist and then left alone forever — a password changed in the
    # Admin Panel is never reverted to this value on the next restart.
    #
    # The built-in default is a KNOWN credential: it ships in this file, so it
    # is public. It exists so the Surat deployment has a working sign-in out of
    # the box, and the server logs a loud warning at every boot while it is
    # still in use. Set BOOTSTRAP_ADMIN_PASSWORD in .env before this instance
    # holds real case data.
    BOOTSTRAP_ADMIN_USERNAME: str = "suratpolice"
    BOOTSTRAP_ADMIN_PASSWORD: str = "Suratpolice@1234"
    BOOTSTRAP_ADMIN_FULL_NAME: str = "Surat City Police — Administrator"
    BOOTSTRAP_ADMIN_UNIT: str = "Surat City Police Commissionerate"
    # Force a password change at first sign-in. False for the shipped default so
    # the documented credential works as documented; set true for real rollouts.
    BOOTSTRAP_ADMIN_FORCE_CHANGE: bool = False

    # Fernet key encrypting face templates and mugshots at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Unset means biometrics are stored in the clear — allowed for local demos,
    # refused when SIMULATION_ENABLED is false (i.e. a real deployment).
    BIOMETRIC_ENCRYPTION_KEY: str = ""

    # Trust X-Forwarded-For for client IPs in the audit log. Enable ONLY when a
    # reverse proxy you control sets that header, otherwise callers can forge it.
    TRUST_PROXY_HEADERS: bool = False

    # Per-identity request budgets (requests per window, window in seconds).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "300/60"      # ordinary reads
    RATE_LIMIT_LOGIN: str = "10/300"        # unauthenticated, per client IP
    RATE_LIMIT_EXPENSIVE: str = "20/60"     # face search, OSINT fetches, LLM calls
    # The voice assistant. Its own budget, deliberately tighter than the general
    # read budget: a hot microphone in a noisy control room can fire a lot of
    # requests, and that must not consume the analyst's own quota.
    RATE_LIMIT_ASSISTANT: str = "40/60"

    # SENTINEL voice assistant (services/assistant/).
    ASSISTANT_ENABLED: bool = True
    # Generous, because the agent answers real questions and not just commands.
    # The transcript is still truncated rather than rejected: a dictation engine
    # that ran on produces a long transcript with a good question at the front.
    ASSISTANT_MAX_QUERY_CHARS: int = 600
    # The tool-calling agent, which handles everything the deterministic rules
    # layer does not recognise. Turning it off leaves those rules working — the
    # nine common questions keep answering with no model involved at all.
    ASSISTANT_LLM_FALLBACK: bool = True
    # The read-only SQL window (services/assistant/sandbox.py). Restricted to
    # three views of structured columns, enforced by the database as well as by
    # a validator, and it cannot reach post text, accounts, the audit trail or
    # the registry. Set false to leave the assistant with curated tools only.
    ASSISTANT_SQL_ENABLED: bool = True
    ASSISTANT_SQL_MIN_ROLE: str = "analyst"

    # ── real-time voice pipeline (services/voice/) ──────────────────────────
    # The streaming channel: microphone → denoise → VAD → STT → end-of-speech →
    # assistant → sentence aggregation → normalisation → TTS. Off does not
    # remove the assistant, only the live audio channel — the typed endpoint
    # and the browser's own Web Speech API keep working.
    VOICE_ENABLED: bool = True

    # Recognition. "browser" needs no key and runs in the client; the rest are
    # server-side and are tried in fallback order when the chosen one has no
    # key. Groq Whisper is the default because the key already exists for the
    # rest of the product and it handles Gujarati and code-mixed speech well.
    VOICE_STT_PROVIDER: str = "groq_whisper"
    VOICE_STT_MODEL: str = "whisper-large-v3-turbo"
    VOICE_STT_LOCAL_MODEL: str = "base"          # openai-whisper size
    VOICE_STT_TIMEOUT: float = 30.0
    # "auto" leaves the language unpinned. Pinning to en makes Whisper
    # transliterate Gujarati into nonsense English rather than transcribing it,
    # and officers switch language mid-sentence.
    VOICE_LANGUAGE: str = "auto"

    # Synthesis. "auto" takes the best voice this deployment has a key for —
    # elevenlabs, then sarvam, then the browser's own — rather than failing
    # when a named provider has no key. The browser end of that ladder costs
    # nothing, adds no round trip, and keeps the answer on the machine, which
    # in a police deployment is an argument in its own right.
    # Name a provider explicitly to pin it. (Groq's playai-tts was here and is
    # decommissioned upstream — see services/voice/transformer/tts.py.)
    VOICE_TTS_PROVIDER: str = "auto"
    #: Optional voice name/id, in the *pinned* provider's namespace. Ignored
    #: when the factory falls back, since voice names are not portable.
    VOICE_TTS_VOICE: str = ""
    VOICE_TTS_TIMEOUT: float = 30.0

    VOICE_VAD_PROVIDER: str = "energy_vad"       # or silero_vad (needs torch)
    VOICE_DENOISER: str = "spectral_gate"        # or passthrough
    # How long a pause means "finished" rather than "thinking". Shortened
    # automatically after terminal punctuation and lengthened after a trailing
    # conjunction — see services/voice/end_of_speech.py.
    VOICE_EOS_SILENCE_SECONDS: float = 1.0

    # Spoken once, on the first connection of a sitting — not on the automatic
    # reconnects that follow an idle close, or an officer would be greeted
    # every few minutes for a whole shift.
    # The microphone is open from sign-in, so with this ON the assistant only
    # answers speech that names Sentinel — which is what a shared control room
    # wants, because otherwise it answers the whole room's conversation aloud.
    #
    # It defaults OFF regardless, and the reason is worth stating: this changes
    # the console's most basic behaviour, and when it is on, every utterance
    # that does not name Sentinel produces *silence*. That is indistinguishable
    # from a broken microphone to anyone who has not been told, which is
    # exactly how it was first experienced here. A feature whose failure mode
    # looks identical to a bug does not belong on by default; a single
    # operator at a desk gains nothing from it and loses the ability to just
    # talk. Turn it on for a shared room.
    VOICE_WAKE_WORD_ENABLED: bool = False
    # After an answer, the officer is mid-conversation and should not have to
    # say the name again — "Sentinel, brief me on Surat" / "and Rajkot?" is one
    # exchange, not two. Speaking again extends the window; silence closes it,
    # which is exactly when the officer has turned back to the room.
    VOICE_WAKE_FOLLOW_UP_SECONDS: float = 20.0
    VOICE_GREETING: str = ("Sentinel online. Say “Sentinel” and then "
                           "your question whenever you need me.")
    # A microphone left open is a privacy problem as much as a cost one, so an
    # unused session closes itself rather than waiting to be remembered. The
    # browser reconnects transparently, so an officer never sees this happen;
    # it is longer than it was only because the assistant is now always on and
    # a five-minute close/reopen cycle was pure churn.
    VOICE_IDLE_TIMEOUT: float = 900.0
    VOICE_MAX_SESSION_SECONDS: float = 1800.0
    VOICE_MAX_CONCURRENT_SESSIONS: int = 8

    # Optional provider keys. Absent means the provider is skipped by the
    # factory's fallback walk, never an error.
    SARVAM_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_MODEL: str = "eleven_turbo_v2_5"

    # Local neural voice (kokoro-onnx). Weights are not shipped and are not
    # fetched on demand — see app/services/voice/bootstrap.py. Until they are
    # on disk the provider reports unavailable and the ladder walks past it,
    # so an unprepared machine still talks, just through the browser.
    KOKORO_MODEL_DIR: str = str(BASE_DIR / "models" / "kokoro")
    #: Blank follows the session language: an American voice for English, a
    #: Hindi one for Hindi or Gujarati. Set it to pin one regardless.
    KOKORO_VOICE: str = ""
    # A separately installed Piper HTTP server, e.g.
    # http://127.0.0.1:5000 — deliberately out-of-process, because piper-tts
    # is GPL-3.0 and importing it would relicense this backend.
    PIPER_HTTP_URL: str = ""
    PIPER_VOICE: str = ""

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
    # Models that support function calling, in preference order. The assistant
    # walks this chain instead of the general one: a model that ignores the
    # `tools` parameter answers from memory, and an assistant whose safety
    # rests on "it only sees what tools return" must never do that.
    GROQ_TOOL_MODELS: list[str] = [
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b",
        "llama-3.1-8b-instant",
    ]
    GROQ_VERIFY_MIN_SCORE: int = 55
    GROQ_MAX_PER_TICK: int = 8
    GROQ_TIMEOUT_SECONDS: int = 20

    # Ollama — a model running on this machine, tried when every Groq model in
    # the chain has failed, and the only LLM at all when there is no Groq key.
    # It is what keeps the assistant answering through a drained free tier, a
    # dropped uplink, or an air-gapped installation, none of which are
    # hypothetical for a police control room.
    #
    # Blank disables it. Point it at a running `ollama serve`, e.g.
    #   OLLAMA_BASE_URL=http://127.0.0.1:11434
    OLLAMA_BASE_URL: str = ""
    OLLAMA_MODEL: str = "llama3.1:8b"
    # Tool calling is a *separate* switch, and blank by default even when a
    # model is configured. A local model that accepts the `tools` parameter and
    # then answers from memory is the one failure this assistant cannot absorb:
    # its whole safety story is that it only ever sees what a tool returned.
    # Set this only to a model verified to call tools — llama3.1, qwen2.5 and
    # mistral-nemo do; most small local models do not.
    OLLAMA_TOOL_MODEL: str = ""
    # Local inference on CPU is far slower than Groq. The timeout is generous
    # because the alternative to a slow answer here is no answer at all.
    OLLAMA_TIMEOUT_SECONDS: int = 120

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
    # Seed handles, same shape as REDDIT_SUBREDDITS/TELEGRAM_CHANNELS and read
    # by whichever Instagram adapter is live. Defaulted rather than left empty:
    # with no seeds the collector silently falls back to watchlist hashtags
    # only, which looks like "Instagram is configured but returns nothing".
    # These two are the handles the README documents; add Vadodara/Rajkot
    # civic pages here as they are verified.
    # Every handle here was resolved against the live private API before being
    # added. That check is the whole point of the list: a handle that does not
    # exist costs a failed lookup every cycle and then silently contributes
    # nothing, which is indistinguishable from a city simply being quiet.
    # "suratsmartcity" was exactly that — it had been the documented Surat seed
    # since the beginning and does not resolve, so Surat had no civic page at
    # all while appearing configured.
    IG_SEED_USERNAMES_RAW: list[str] = [
        "amdavadamc:Ahmedabad",       # Ahmedabad Municipal Corporation — 91k
        "suratcitypolice:Surat",      # Surat City Police — 443k
        "vmcvadodara:Vadodara",       # Vadodara Municipal Corporation — 94k
        # Rajkot still needs a verified handle: the public fallback route was
        # rate-limited when the others were checked, so no candidate has been
        # confirmed rather than one having been rejected.
    ]

    @property
    def IG_SEED_USERNAMES(self) -> list[tuple[str, str]]:
        out = []
        for entry in self.IG_SEED_USERNAMES_RAW:
            source, _, city = entry.partition(":")
            if source.strip():
                out.append((source.strip(), city.strip()))
        return out

    # Instagram via instagrapi (unofficial, no Meta app review) — credentials of
    # a real IG account (use a dedicated burner). Activates the
    # "Instagram (instagrapi)" adapter only when no Graph API token is set;
    # the session persists in backend/ig_session.json. IG_SESSIONID is the
    # `sessionid` cookie from a logged-in browser and is preferred: it skips the
    # fresh-login handshake that usually triggers Instagram's checkpoint.
    IG_SESSIONID: str = ""
    IG_USERNAME: str = ""
    IG_PASSWORD: str = ""
    # Private-API reads get an account blocked far faster than Graph calls, so
    # this politeness gap is deliberately wider than CRAWL_MIN_INTERVAL_SECONDS.
    IG_MIN_INTERVAL_SECONDS: int = 1800
    # Comment threads are where municipal grievances actually live — the caption
    # is usually a press release. Each media costs one extra private-API call
    # though, so only the most-commented media of a cycle get one. Set the
    # media cap to 0 to collect captions only.
    IG_COMMENTS_MAX_MEDIA_PER_CYCLE: int = 8
    IG_COMMENTS_PER_MEDIA: int = 20
    # Hashtag reads per cycle. Instagram throttles these hardest of all, so the
    # watchlist is walked a slice at a time and the starting point advances
    # each cycle — every term gets covered, just spread over the day rather
    # than all at once (the same tactic the YouTube adapter uses for quota).
    IG_HASHTAGS_PER_CYCLE: int = 3
    # Accounts on the watchlist (kind="account") read per cycle, same rotation.
    # These are pulled *in addition to* IG_SEED_USERNAMES: seeds are the civic
    # pages this deployment always watches, these are the handles an officer
    # added. 0 disables the leg.
    IG_WATCHED_ACCOUNTS_PER_CYCLE: int = 4
    # Author profile lookups per cycle. Media found through a hashtag carries
    # only a UserShort — no follower count, no reliable verified flag — so a
    # viral unknown account would be scored as having zero reach. This budget
    # buys back the real numbers for the highest-engagement authors of the
    # cycle; results are cached for IG_PROFILE_TTL_HOURS. 0 disables it.
    IG_PROFILE_LOOKUPS_PER_CYCLE: int = 5
    IG_PROFILE_TTL_HOURS: int = 24

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

if "*" in settings.CORS_ORIGINS:
    raise RuntimeError(
        "CORS_ORIGINS contains '*'. With credentialed requests that lets any "
        "site an officer visits drive this API as them. List the dashboard "
        "origins explicitly, e.g. CORS_ORIGINS=[\"https://sentinel.gujarat.gov.in\"]."
    )

# A wildcard Host is tolerable while this is a demo against simulated data; on
# a real deployment it re-opens Host-header injection, so it is refused there.
if "*" in settings.ALLOWED_HOSTS and not settings.SIMULATION_ENABLED:
    raise RuntimeError(
        "ALLOWED_HOSTS contains '*' on a live deployment. Name the hostnames "
        "this API is reached by, e.g. ALLOWED_HOSTS=[\"sentinel.gujarat.gov.in\"]."
    )

# The origins the dashboard is served from are, by definition, hosts this API is
# addressed as in a same-host deployment. Folding them in keeps one list to edit.
for _origin in settings.CORS_ORIGINS:
    _host = _origin.split("://")[-1].split("/")[0].split(":")[0]
    if _host and _host not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS.append(_host)

THREAT_LABELS = ["Incitement to Violence", "Inflammatory", "Fake News", "Neutral"]
