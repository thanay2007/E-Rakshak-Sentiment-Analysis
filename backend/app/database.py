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
    # Added with the 3-model sentiment ensemble but never given a migration, so
    # any database created before it fails at startup with "no such column".
    # Matches the other JSON columns on this table: nullable, no SQL default —
    # the model's default_factory=dict supplies {} for new rows, and existing
    # rows read back as NULL, which the serializer already tolerates.
    ("post", "sentiment_consensus", "JSON"),
    # Chain-of-custody attribution. Existing rows keep empty actor fields, which
    # is honest: those actions genuinely were taken before authentication
    # existed, and backfilling a name onto them would be fabricating evidence.
    ("auditlog", "actor_id", "TEXT NOT NULL DEFAULT ''"),
    ("auditlog", "actor_username", "TEXT NOT NULL DEFAULT ''"),
    ("auditlog", "actor_role", "TEXT NOT NULL DEFAULT ''"),
    ("auditlog", "actor_badge", "TEXT NOT NULL DEFAULT ''"),
    ("auditlog", "ip", "TEXT NOT NULL DEFAULT ''"),
    ("auditlog", "user_agent", "TEXT NOT NULL DEFAULT ''"),
]

# The audit log is append-only, enforced in the database rather than in Python.
# An application-level rule protects nothing against a bug, a stray ORM cascade,
# or anyone who opens the .db file — which is exactly the population a
# chain-of-custody log needs protecting from.
_APPEND_ONLY_TRIGGERS = [
    ("auditlog_no_update", """
        CREATE TRIGGER IF NOT EXISTS auditlog_no_update
        BEFORE UPDATE ON auditlog
        BEGIN SELECT RAISE(ABORT, 'auditlog is append-only'); END;
    """),
    ("auditlog_no_delete", """
        CREATE TRIGGER IF NOT EXISTS auditlog_no_delete
        BEFORE DELETE ON auditlog
        BEGIN SELECT RAISE(ABORT, 'auditlog is append-only'); END;
    """),
    ("facesearchlog_no_update", """
        CREATE TRIGGER IF NOT EXISTS facesearchlog_no_update
        BEFORE UPDATE ON facesearchlog
        BEGIN SELECT RAISE(ABORT, 'facesearchlog is append-only'); END;
    """),
    ("facesearchlog_no_delete", """
        CREATE TRIGGER IF NOT EXISTS facesearchlog_no_delete
        BEFORE DELETE ON facesearchlog
        BEGIN SELECT RAISE(ABORT, 'facesearchlog is append-only'); END;
    """),
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
            for _name, ddl in _APPEND_ONLY_TRIGGERS:
                conn.exec_driver_sql(ddl)
            conn.commit()


def get_session():
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope():
    with Session(engine) as session:
        yield session
