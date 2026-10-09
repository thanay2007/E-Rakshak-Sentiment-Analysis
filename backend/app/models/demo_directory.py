"""Standalone fictional records for manual directory demonstrations."""
from sqlalchemy import JSON, Column, LargeBinary
from sqlmodel import Field, SQLModel


DEMO_LABEL = "Synthetic demo data — not a real criminal record"


class DemoDirectoryProfile(SQLModel, table=True):
    id: str = Field(primary_key=True)
    full_name: str = Field(index=True)
    role: str
    bio: str
    image_alt: str
    image_source: str
    image_prompt: str
    image_png: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    case_history: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
