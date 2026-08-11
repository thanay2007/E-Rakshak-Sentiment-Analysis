"""SQLModel tables. JSON columns keep the schema portable between SQLite and Postgres."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Post(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    content_hash: str = Field(index=True, unique=True)
    platform: str = Field(index=True)                 # X | Facebook | Instagram | Reddit | Telegram
    author_handle: str = Field(index=True)
    # Platform-side account id, when the adapter can get one ("" otherwise).
    # Indexed because the OSINT question is "everything this account posted",
    # and a handle can be renamed out from under that query while the id cannot.
    author_id: str = Field(default="", index=True)
    author_name: str = ""
    author_followers: int = 0
    author_verified: bool = False
    author_account_age_days: int = 0

    text: str
    translation: str = ""                             # English gloss for the analyst
    language: str = Field(default="English", index=True)  # Gujarati | Hindi | Hinglish | English | Mixed
    code_mixed: bool = False

    # The post's tag. This is the only category the system assigns — it does not
    # claim a post "is incitement" or "is fake news", which are investigative
    # conclusions rather than properties of the text (see ml/classifier.py).
    sentiment_label: str = Field(default="neutral", index=True)  # positive | neutral | negative
    sentiment_score: float = 0.0                      # -1 .. +1
    sentiment_confidence: float = 0.0                 # 0 .. 1, ensemble confidence
    # 3-model consensus + Groq final check (ml/ensemble.py): per-model votes,
    # chosen_by, agreement, context adjustments, score breakdown and the full
    # evidence provenance shown in the post drawer.
    sentiment_consensus: dict = Field(default_factory=dict, sa_column=Column(JSON))
    intent: str = "informational"                     # informational | opinion | call_to_action | rumor
    # Ensemble-averaged probability over negative/neutral/positive.
    class_probs: dict = Field(default_factory=dict, sa_column=Column(JSON))
    hate_flags: list = Field(default_factory=list, sa_column=Column(JSON))
    toxicity_score: float = 0.0
    concern_score: float = Field(default=0.0, index=True)  # 0..100, formula in ml/score.py
    keywords: list = Field(default_factory=list, sa_column=Column(JSON))
    hashtags: list = Field(default_factory=list, sa_column=Column(JSON))

    location: str = Field(default="", index=True)
    latitude: float = 0.0
    longitude: float = 0.0
    engagement: dict = Field(default_factory=dict, sa_column=Column(JSON))  # likes/shares/comments/views
    url: str = ""
    media_urls: list = Field(default_factory=list, sa_column=Column(JSON))  # attached image/video URLs
    cluster_id: str = Field(default="", index=True)   # coordinated-burst id ("" = organic)
    is_amplified: bool = False

    # Groq LLM second-opinion verdict (services/groq_verifier.py): model,
    # llm labels, confidence, reason, agrees/disagrees, overridden flag.
    llm_verification: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Cross-source corroboration for suspected fake news (services/fact_check.py):
    # verdict, matching news headlines, query used.
    fact_check: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Analyst-grade dossier (services/evidence.py): claims individually assessed,
    # verbatim evidence phrases, cited news sources, risk + recommended action.
    evidence_report: dict = Field(default_factory=dict, sa_column=Column(JSON))

    true_label: str = ""                              # ground truth for simulated posts (accuracy metrics)
    created_at: datetime = Field(default_factory=utcnow, index=True)   # when posted on the platform
    ingested_at: datetime = Field(default_factory=utcnow)


class Alert(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    post_id: str = Field(index=True)
    severity: str = Field(default="high", index=True)  # critical | high | medium
    status: str = Field(default="new", index=True)     # new | acknowledged | escalated
    title: str
    summary: str = ""
    category: str = ""                                 # the post's sentiment tag
    location: str = ""
    platform: str = ""
    concern_score: float = 0.0
    escalation: dict = Field(default_factory=dict, sa_column=Column(JSON))  # auto-generated escalation template
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class WatchlistItem(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    kind: str = Field(index=True)                      # keyword | hashtag | account | location
    value: str
    note: str = ""
    priority: str = Field(default="medium", index=True)  # low | medium | high | critical
    category: str = ""                                 # analyst grouping / preset pack name
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Report(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    title: str
    kind: str = "incident"                             # incident | escalation
    period_hours: int = 24
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    pdf_path: str = ""
    # Rendered alongside the PDF from the same payload. A stored path rather
    # than one derived from the id, so "this was rendered" stays distinct from
    # "a file of that name might exist": a renderer whose library is missing
    # returns "", and the download endpoint 404s on that exactly as it already
    # does for a missing PDF.
    xlsx_path: str = ""
    created_at: datetime = Field(default_factory=utcnow, index=True)

class Suspect(SQLModel, table=True):
    """A person of record — the database faces detected in evidence are matched
    against (osint/face_db.py).

    Holds three layers that the identification flow stitches together:
      1. identity        — name, aliases, physical/demographic descriptors
      2. the record      — case IDs, charges, custody status, jurisdiction
      3. OSINT linkage   — known social handles, which drive the dossier pull
    plus the biometric templates themselves in `face_templates`.
    """
    id: str = Field(default_factory=_uuid, primary_key=True)
    full_name: str = Field(index=True)
    aliases: list = Field(default_factory=list, sa_column=Column(JSON))

    # criminal | wanted | person_of_interest | missing | cleared
    record_type: str = Field(default="person_of_interest", index=True)
    risk_level: str = Field(default="medium", index=True)   # low | medium | high | critical
    # at_large | in_custody | on_bail | convicted | acquitted | under_investigation
    status: str = Field(default="under_investigation", index=True)

    case_ids: list = Field(default_factory=list, sa_column=Column(JSON))   # FIR / case numbers
    charges: list = Field(default_factory=list, sa_column=Column(JSON))    # [{section, description, status, date}]
    convictions: int = 0
    jurisdiction: str = ""                                # police station / district owning the record
    last_known_location: str = Field(default="", index=True)
    wanted_since: str = ""                                # free-text date on the warrant

    gender: str = ""
    age: int = 0
    nationality: str = ""
    identifying_marks: str = ""
    notes: str = ""

    # [{platform, handle, url, note}] — the handles the dossier builder expands
    social_handles: list = Field(default_factory=list, sa_column=Column(JSON))

    # [{id, vector[128], quality, source, added_at, thumb}] — reference templates
    face_templates: list = Field(default_factory=list, sa_column=Column(JSON))
    photo_thumb: str = ""                                 # data-URI mugshot for the registry UI

    source: str = "analyst"                               # analyst | seed | import
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class FaceSearchLog(SQLModel, table=True):
    """Every face query run against the registry, kept for chain of custody.

    Biometric searches are the most consequential lookup in this system, so the
    probe's own hash, what it matched and at what distance are recorded
    separately from the general AuditLog.
    """
    id: str = Field(default_factory=_uuid, primary_key=True)
    image_sha256: str = Field(default="", index=True)
    filename: str = ""
    faces_detected: int = 0
    identified_count: int = 0
    results: list = Field(default_factory=list, sa_column=Column(JSON))  # [{suspect_id, name, distance, band}]
    created_at: datetime = Field(default_factory=utcnow, index=True)


class AuditLog(SQLModel, table=True):
    """Append-only log of analyst actions for chain-of-custody compliance.

    Every row names the officer who performed the action. An entry without an
    actor is worthless in court — "a face search happened" answers nothing if
    it cannot answer "who ran it". UPDATE and DELETE are blocked on this table
    by database triggers installed in database.py, so history cannot be
    rewritten through the ORM or by anyone holding a SQL connection.
    """
    id: str = Field(default_factory=_uuid, primary_key=True)
    action: str = Field(index=True)                    # e.g., "alert_escalated", "report_generated", "osint_lookup"
    target_id: str = Field(default="")                 # the ID of the affected resource

    # Who did it. Denormalised on purpose: the username/role/badge are copied in
    # at write time so the record still reads correctly after the user account
    # is renamed, demoted or deactivated.
    actor_id: str = Field(default="", index=True)
    actor_username: str = Field(default="", index=True)
    actor_role: str = Field(default="")
    actor_badge: str = Field(default="")
    # Where from. Both are attacker-influenced (proxy headers, UA string) and are
    # recorded as corroborating detail, never as an authentication signal.
    ip: str = Field(default="")
    user_agent: str = Field(default="")

    details: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class User(SQLModel, table=True):
    """An officer with access to the system.

    Passwords are stored as scrypt hashes (services/security.py) — never
    reversible, never logged. `token_version` is the revocation lever: bumping
    it invalidates every JWT already issued to this user, which is what makes
    "force logout" and "deactivate account" take effect immediately rather than
    whenever the current token happens to expire.
    """
    id: str = Field(default_factory=_uuid, primary_key=True)
    username: str = Field(index=True, unique=True)
    full_name: str = ""
    badge_number: str = ""
    unit: str = ""                                     # police station / district

    # analyst | supervisor | admin — hierarchy defined in app/security/roles.py
    role: str = Field(default="analyst", index=True)

    password_hash: str = ""
    password_changed_at: datetime = Field(default_factory=utcnow)
    must_change_password: bool = False

    active: bool = Field(default=True, index=True)
    # Lockout counters — cleared on any successful login.
    failed_attempts: int = 0
    locked_until: datetime | None = Field(default=None)
    last_login_at: datetime | None = Field(default=None)
    last_login_ip: str = ""

    token_version: int = 0
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)

