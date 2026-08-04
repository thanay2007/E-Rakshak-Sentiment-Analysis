"""Engine and schema lifecycle.

Two supported targets, chosen entirely by DATABASE_URL:

  sqlite      zero-setup default. The whole corpus is one file next to the app.
  postgres    Supabase or any Postgres. The corpus becomes durable and shared:
              several officers, several processes and a redeploy all see the
              same history instead of whatever happens to be on one machine.

**Alembic owns the schema.** This module used to call
`SQLModel.metadata.create_all()` and then patch in missing columns by hand from
a list kept here. That combination is quietly broken: create_all() does nothing
to a table that already exists, so the hand-written patch list was the only
thing keeping older databases alive, and every new column had to be remembered
in two places. Now there is one place — `alembic/versions/` — and both a fresh
Supabase project and a year-old SQLite file reach the same schema by running
the same migrations.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine

from app.config import BASE_DIR, settings

log = logging.getLogger("sentinel.db")

IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")
IS_POSTGRES = settings.DATABASE_URL.startswith(("postgresql", "postgres://"))

ALEMBIC_INI = Path(BASE_DIR) / "alembic.ini"

# Tables that prove a database predates migrations being wired up. If these
# exist with no alembic_version, the schema came from the old create_all() path.
_LEGACY_MARKERS = ("post", "alert", "watchlistitem")


def _make_engine():
    if IS_SQLITE:
        return create_engine(settings.DATABASE_URL, echo=settings.DB_ECHO,
                             connect_args={"check_same_thread": False})
    # Hosted Postgres (Supabase) closes idle connections behind a pooler, so a
    # pooled connection can be dead by the time it is handed out. pool_pre_ping
    # turns that from a failed request into a transparent reconnect.
    return create_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    )


engine = _make_engine()


def _alembic_config(connection) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(Path(BASE_DIR) / "alembic"))
    # % doubled because Config writes into configparser, which would otherwise
    # read the %40 of a percent-encoded password as its own interpolation
    # syntax and raise. configparser un-doubles it on read. See alembic/env.py.
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))
    # Hand the live connection to env.py so migrations run on the same engine
    # the API uses, rather than opening a second one against the same file —
    # which SQLite will happily let you do and then lock.
    cfg.attributes["connection"] = connection
    return cfg


def _head_revision() -> str | None:
    script = ScriptDirectory(str(Path(BASE_DIR) / "alembic"))
    return script.get_current_head()


def init_db() -> None:
    """Bring the database up to the latest migration.

    Three states are possible on boot and all three are handled here, because
    the alternative is a README step that someone will skip:

      empty          → run every migration
      pre-migration  → tables exist but no alembic_version. The schema already
                       matches 0001 (both were generated from the same models),
                       so stamp it and run what follows rather than trying to
                       CREATE TABLE over live data.
      up to date     → nothing to do
    """
    from app import models  # noqa: F401 — registers tables on SQLModel.metadata

    # Checked here rather than at config import, so that unit tests which never
    # touch a database still run. The alternative to catching it at all is a
    # psycopg stack trace during startup that says nothing about what to do.
    if "YOUR-DB-PASSWORD" in settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL still has the placeholder password in it.\n\n"
            "  Supabase dashboard -> Project Settings -> Database ->\n"
            "  Reset database password, then replace YOUR-DB-PASSWORD in\n"
            "  backend/.env with the value it shows you (it is shown once).\n\n"
            "  Check it with:  python -m app.check_db\n"
        )

    if not settings.AUTO_MIGRATE:
        log.warning("AUTO_MIGRATE is off — run 'alembic upgrade head' yourself.")
        return

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        current = context.get_current_revision()
        tables = set(inspect(connection).get_table_names())
        cfg = _alembic_config(connection)

        if current is None and all(t in tables for t in _LEGACY_MARKERS):
            # Adopt an existing database created before migrations existed.
            log.warning(
                "Existing tables found with no migration history — stamping as "
                "'0001_baseline' and applying anything newer. No data is touched.")
            command.stamp(cfg, "0001_baseline")

        command.upgrade(cfg, "head")

    log.info("database ready (%s) at revision %s",
             "sqlite" if IS_SQLITE else "postgres", _head_revision())


def get_session():
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope():
    with Session(engine) as session:
        yield session
