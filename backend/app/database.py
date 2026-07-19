from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)


# Columns added after first release — create_all() never ALTERs an existing
# table, so pre-existing SQLite databases get them patched in here.
_COLUMN_MIGRATIONS = [
    ("watchlistitem", "priority", "TEXT NOT NULL DEFAULT 'medium'"),
    ("watchlistitem", "category", "TEXT NOT NULL DEFAULT ''"),
]


def init_db() -> None:
    from app import models  # noqa: F401 — register tables

    SQLModel.metadata.create_all(engine)
    if settings.DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            for table, col, ddl in _COLUMN_MIGRATIONS:
                cols = [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
                if cols and col not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            conn.commit()


def get_session():
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope():
    with Session(engine) as session:
        yield session
