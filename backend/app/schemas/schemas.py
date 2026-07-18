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
    active: bool = True


class WatchlistUpdate(BaseModel):
    value: Optional[str] = None
    note: Optional[str] = None
    active: Optional[bool] = None


class ReportRequest(BaseModel):
    title: str = ""
    period_hours: int = 24
    kind: str = "incident"
