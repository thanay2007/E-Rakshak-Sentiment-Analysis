"""Preflight for whatever DATABASE_URL points at.

    python -m app.check_db

Answers the questions you actually have when a database will not come up, in
the order you ask them: which database is this, can I reach it, is the schema
current, is anything in it, and are the audit guarantees really in place.

Read-only apart from `--migrate`, so it is safe to run against production.
"""
from __future__ import annotations

import sys
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import inspect, text
from sqlmodel import Session, func, select

from app.config import settings

PASS, FAIL, WARN = "  ok  ", " FAIL ", " warn "


def _redacted(url: str) -> str:
    """The URL with the password starred out, so this is safe to paste."""
    parts = urlsplit(url)
    if not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, f"{parts.username}:****@{host}",
                       parts.path, parts.query, parts.fragment))


def main(argv: list[str]) -> int:
    from app.database import IS_POSTGRES, IS_SQLITE, engine

    url = settings.DATABASE_URL
    print(f"\nDATABASE_URL  {_redacted(url)}")

    # Name Supabase explicitly. "postgresql://" in the URL reads like a
    # different product to anyone who has not been told that Supabase *is*
    # hosted Postgres, so say so rather than printing a dialect name.
    if "supabase" in url:
        parts = urlsplit(url)
        ref = (parts.username or "").partition(".")[2]
        print(f"storage       SUPABASE  (project {ref or 'unknown'})")
        print("              a Supabase project is a hosted PostgreSQL database,")
        print("              which is why the URL says postgresql://")
    elif IS_SQLITE:
        print("storage       local SQLite file — NOT Supabase")
    else:
        print("storage       PostgreSQL (not Supabase)")
    print()

    if "YOUR-DB-PASSWORD" in settings.DATABASE_URL:
        print(f"{FAIL} DATABASE_URL still contains the placeholder password.")
        print("       Supabase dashboard -> Project Settings -> Database ->")
        print("       Reset database password, then paste it into backend/.env\n")
        return 1

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"{FAIL} cannot connect\n")
        detail = str(exc).split("\n")[0]
        print(f"       {detail}\n")
        low = detail.lower()
        if "password authentication failed" in low:
            print("       The password is wrong. Reset it in the Supabase")
            print("       dashboard — the one shown at project creation is the")
            print("       only time it is displayed.")
        elif "tenant or user not found" in low or "enotfound" in low:
            print("       Wrong pooler host or username. The username must be")
            print("       postgres.<project-ref>, not plain 'postgres'.")
        elif "timeout" in low or "unreachable" in low or "network" in low:
            print("       Unreachable. If the host is db.<ref>.supabase.co, that")
            print("       is IPv6-only — use the pooler host on port 5432.")
        print()
        return 1

    print(f"{PASS} connected")

    if settings.DATABASE_URL.startswith("sqlite"):
        print(f"{WARN} this is a local file, not a shared database.")
        print("       Set DATABASE_URL to Supabase for durable storage.")

    # ── schema ──────────────────────────────────────────────────────────────
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext
    from app.database import ALEMBIC_INI  # noqa: F401 — proves it resolves
    from pathlib import Path
    from app.config import BASE_DIR

    head = ScriptDirectory(str(Path(BASE_DIR) / "alembic")).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        tables = set(inspect(conn).get_table_names())

    if current == head:
        print(f"{PASS} schema at head ({head})")
    elif current is None:
        print(f"{WARN} no migrations applied yet (head is {head})")
        print("       Start the backend, or run: alembic upgrade head")
    else:
        print(f"{FAIL} schema is at {current}, head is {head}")
        print("       Run: alembic upgrade head")

    expected = {"post", "alert", "watchlistitem", "report", "suspect",
                "user", "auditlog", "facesearchlog"}
    missing = expected - tables
    print(f"{FAIL if missing else PASS} tables"
          f"{f' — MISSING {sorted(missing)}' if missing else f' ({len(expected)}/8)'}")

    # ── contents ────────────────────────────────────────────────────────────
    if not missing:
        from app.models import (Alert, AuditLog, FaceSearchLog, Post, Report,
                                Suspect, User, WatchlistItem)
        print("\n  rows")
        with Session(engine) as s:
            for model in (Post, Alert, Report, WatchlistItem, Suspect, User,
                          AuditLog, FaceSearchLog):
                n = s.exec(select(func.count()).select_from(model)).one()
                print(f"    {model.__name__:<15} {n:>8,}")

    # ── the append-only guarantee ───────────────────────────────────────────
    print()
    if "auditlog" in tables:
        with engine.connect() as conn:
            if settings.DATABASE_URL.startswith("sqlite"):
                found = {r[0] for r in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"))}
                want = {"auditlog_no_update", "auditlog_no_delete",
                        "facesearchlog_no_update", "facesearchlog_no_delete"}
            else:
                found = {r[0] for r in conn.execute(text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))}
                want = {"auditlog_append_only", "facesearchlog_append_only"}
        absent = want - found
        if absent:
            print(f"{FAIL} audit trail is NOT protected — missing {sorted(absent)}")
            print("       Run: alembic upgrade head")
        else:
            print(f"{PASS} audit trail is append-only in the database")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
