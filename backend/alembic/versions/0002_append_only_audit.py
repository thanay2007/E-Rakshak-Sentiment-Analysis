"""Make the audit tables append-only in the database itself.

Revision ID: 0002_append_only
Revises: 0001_baseline
Create Date: 2026-08-04

`auditlog` and `facesearchlog` answer "who investigated whom, and when". A log
that can be edited answers nothing, so UPDATE and DELETE are refused by the
database rather than by a convention in the ORM layer. An application-level
rule protects nothing against a bug, a stray cascade, or anyone who opens a SQL
connection — which is exactly the population a chain-of-custody log exists to
protect against.

Written per dialect because there is no portable way to express it:

  SQLite    BEFORE UPDATE / BEFORE DELETE triggers calling RAISE(ABORT).
  Postgres  one plpgsql function raising `restrict_violation`, wired to a
            BEFORE UPDATE OR DELETE trigger on each table.

Consequence worth knowing before you hit it: a bulk import that re-runs and
tries to re-insert an existing audit row will issue an UPDATE and be refused.
That is the guarantee working, not a bug — see docs/SUPABASE.md.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_append_only"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("auditlog", "facesearchlog")

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION sentinel_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == "sqlite":
        for table in TABLES:
            for operation in ("UPDATE", "DELETE"):
                # The trailing END; is part of the trigger body, not a
                # statement terminator — SQLite requires it.
                op.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} "
                    f"BEFORE {operation} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                )
        return

    if dialect == "postgresql":
        op.execute(_PG_FUNCTION)
        for table in TABLES:
            # No CREATE TRIGGER IF NOT EXISTS in Postgres. Dropping first is
            # safe: the definition is fixed here, not user data.
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
            op.execute(
                f"CREATE TRIGGER {table}_append_only "
                f"BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION sentinel_append_only()"
            )
        return

    raise RuntimeError(
        f"No append-only implementation for dialect {dialect!r}. Add one before "
        f"running SENTINEL on it — silently skipping would leave the audit "
        f"trail editable while the Security Posture page reported it protected."
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in TABLES:
            for operation in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{operation}")
    elif dialect == "postgresql":
        for table in TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute("DROP FUNCTION IF EXISTS sentinel_append_only()")
