from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)


def init_db() -> None:
    from app import models  # noqa: F401 — register tables

    SQLModel.metadata.create_all(engine)
    _migrate(engine)


def _migrate(eng) -> None:
    """Additive micro-migrations for columns create_all won't add to an
    existing table (SQLite). Safe to run on every boot."""
    from sqlalchemy import inspect, text

    cols = {c["name"] for c in inspect(eng).get_columns("post")}
    if "llm_verification" not in cols:
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE post ADD COLUMN llm_verification JSON"))


def get_session():
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope():
    with Session(engine) as session:
        yield session
