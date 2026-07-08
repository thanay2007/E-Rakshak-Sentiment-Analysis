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
    platform: str = Field(index=True)                 # X | Facebook | Instagram | YouTube | Reddit | Web
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
    cluster_id: str = Field(default="", index=True)   # coordinated-burst id ("" = organic)
    is_amplified: bool = False

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
