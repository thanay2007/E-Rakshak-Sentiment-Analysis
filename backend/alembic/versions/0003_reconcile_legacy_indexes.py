"""Create indexes that pre-migration databases never got.

Revision ID: 0003_legacy_indexes
Revises: 0002_append_only
Create Date: 2026-08-04

Databases created before Alembic was wired up got their newer columns from a
hand-maintained list of raw `ALTER TABLE ... ADD COLUMN` statements in
database.py. That worked for the columns and silently skipped their indexes,
because an ALTER TABLE says nothing about indexing — so `auditlog.actor_id`,
`auditlog.actor_username` and `watchlistitem.priority` are indexed on a fresh
database and unindexed on an adopted one.

Nobody would have noticed until the audit trail got big enough for "show me
everything officer X did" to start scanning the whole table.

Has to be idempotent: a fresh database already created these in 0001, an
adopted one has not. `CREATE INDEX IF NOT EXISTS` is the one spelling that is
valid on both SQLite (3.8+) and Postgres (9.5+) *and* renders correctly under
`alembic upgrade head --sql`, where there is no live connection to inspect.
"""
from typing import Sequence, Union

import sqlmodel  # noqa: F401 — see alembic/script.py.mako
from alembic import op

revision: str = "0003_legacy_indexes"
down_revision: Union[str, Sequence[str], None] = "0002_append_only"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXPECTED = [
    ("ix_auditlog_actor_id", "auditlog", "actor_id"),
    ("ix_auditlog_actor_username", "auditlog", "actor_username"),
    ("ix_watchlistitem_priority", "watchlistitem", "priority"),
]


def upgrade() -> None:
    for name, table, column in EXPECTED:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})")


def downgrade() -> None:
    # Left in place deliberately. These indexes are part of the baseline
    # schema; dropping them here would make a downgrade to 0002 produce a
    # database that differs from one built by 0001 alone.
    pass
