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
    author_name: str = ""
    author_followers: int = 0
    author_verified: bool = False
    author_account_age_days: int = 0

    text: str
    translation: str = ""                             # English gloss for the analyst
    language: str = Field(default="English", index=True)  # Gujarati | Hindi | Hinglish | English | Mixed
    code_mixed: bool = False

    sentiment_label: str = "neutral"                  # positive | neutral | negative
    sentiment_score: float = 0.0                      # -1 .. +1
    # 3-model consensus (ml/ensemble.py): per-model votes, chosen_by, agreement
    sentiment_consensus: dict = Field(default_factory=dict, sa_column=Column(JSON))
    intent: str = "informational"                     # informational | opinion | call_to_action | threat | rumor
    threat_label: str = Field(default="Neutral", index=True)
    threat_confidence: float = 0.0
    class_probs: dict = Field(default_factory=dict, sa_column=Column(JSON))
    hate_flags: list = Field(default_factory=list, sa_column=Column(JSON))
    toxicity_score: float = 0.0
    threat_score: float = Field(default=0.0, index=True)  # 0..100, formula in ml/threat_score.py
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
    category: str = ""
    location: str = ""
    platform: str = ""
    threat_score: float = 0.0
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
    created_at: datetime = Field(default_factory=utcnow, index=True)

class AuditLog(SQLModel, table=True):
    """Immutable log of analyst actions for chain-of-custody compliance."""
    id: str = Field(default_factory=_uuid, primary_key=True)
    action: str = Field(index=True)                    # e.g., "alert_escalated", "report_generated", "osint_lookup"
    target_id: str = Field(default="")                 # the ID of the affected resource
    details: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)

