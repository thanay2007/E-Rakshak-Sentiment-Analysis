"""Pydantic I/O schemas shared by crawlers and the API layer."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RawPost(BaseModel):
    """What every collector adapter emits — the NLP pipeline enriches it from here."""

    platform: str
    author_handle: str
    author_name: str = ""
    author_followers: int = 0
    author_verified: bool = False
    author_account_age_days: int = 365
    text: str
    translation: str = ""          # simulated posts carry their own gloss; real ones get MT in full mode
    hashtags: list[str] = []
    location: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    engagement: dict = {}
    url: str = ""
    media_urls: list[str] = []     # direct image/video URLs attached to the post
    cluster_id: str = ""
    is_amplified: bool = False
    true_label: str = ""
    created_at: Optional[datetime] = None


class FeedPage(BaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int


class WatchlistCreate(BaseModel):
    kind: str
    value: str
    note: str = ""
    priority: str = "medium"
    category: str = ""
    active: bool = True


class WatchlistUpdate(BaseModel):
    value: Optional[str] = None
    note: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    active: Optional[bool] = None


class SocialHandleIn(BaseModel):
    platform: str = ""
    handle: str
    url: str = ""
    note: str = ""


class ChargeIn(BaseModel):
    section: str = ""              # e.g. "IPC 153A"
    description: str = ""
    status: str = ""               # charged | under trial | convicted | acquitted
    date: str = ""                 # free text — records arrive in many formats


class SuspectCreate(BaseModel):
    full_name: str
    aliases: list[str] = []
    record_type: str = "person_of_interest"
    risk_level: str = "medium"
    status: str = "under_investigation"
    case_ids: list[str] = []
    charges: list[ChargeIn] = []
    convictions: int = 0
    jurisdiction: str = ""
    last_known_location: str = ""
    wanted_since: str = ""
    gender: str = ""
    age: int = 0
    nationality: str = ""
    identifying_marks: str = ""
    notes: str = ""
    social_handles: list[SocialHandleIn] = []


class SuspectUpdate(BaseModel):
    full_name: Optional[str] = None
    aliases: Optional[list[str]] = None
    record_type: Optional[str] = None
    risk_level: Optional[str] = None
    status: Optional[str] = None
    case_ids: Optional[list[str]] = None
    charges: Optional[list[ChargeIn]] = None
    convictions: Optional[int] = None
    jurisdiction: Optional[str] = None
    last_known_location: Optional[str] = None
    wanted_since: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    nationality: Optional[str] = None
    identifying_marks: Optional[str] = None
    notes: Optional[str] = None
    social_handles: Optional[list[SocialHandleIn]] = None
    active: Optional[bool] = None


class ReportRequest(BaseModel):
    title: str = ""
    period_hours: int = 24
    kind: str = "incident"
