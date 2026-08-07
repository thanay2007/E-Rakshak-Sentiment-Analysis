"""Add post.author_id — the platform-side account id behind a handle.

Revision ID: 0004_post_author_id
Revises: 0003_legacy_indexes
Create Date: 2026-08-07

Handles are not identities. An account can rename itself between two crawls and
every "show me everything this account posted" query silently splits in two,
which is precisely the query that matters when the account is coordinating a
burst. The platform's own id does not change, so it is what the query should
anchor on.

The Instagram (instagrapi) adapter is the first to populate it — the private
API hands back a user pk on every media and every comment. Adapters that cannot
get an id leave it "", so this is additive and nothing needs backfilling: no
existing row loses a value it never had.

Idempotent in the same way as 0003 — a database adopted from the pre-migration
era may already have been ALTER-ed by hand, so both the column and its index
are added only when absent (SQLite cannot drop or re-add a column cheaply, and
`ADD COLUMN` on an existing name is a hard error on every backend).

That check needs a live connection to inspect, which `alembic upgrade --sql`
does not have. Rather than crash the offline render — 0003 is explicit that it
has to keep working — offline mode emits the unguarded ALTER and leaves the
already-exists judgement to whoever reviews the script before running it. The
index keeps its `IF NOT EXISTS` spelling, which needs no inspection and is
valid on both SQLite (3.8+) and Postgres (9.5+).
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 — see alembic/script.py.mako
from alembic import op

revision: str = "0004_post_author_id"
down_revision: Union[str, Sequence[str], None] = "0003_legacy_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_author_id() -> bool:
    """True when the column is already there. Offline (`--sql`) mode has no
    connection to ask — `as_sql` is how the MigrationContext reports that —
    so it answers False and the ALTER always renders."""
    if op.get_context().as_sql:
        return False
    return "author_id" in {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("post")
    }


def upgrade() -> None:
    if not _has_author_id():
        op.add_column(
            "post",
            sa.Column("author_id", sqlmodel.sql.sqltypes.AutoString(),
                      nullable=False, server_default=""),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_post_author_id ON post (author_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_post_author_id")
    if op.get_context().as_sql or _has_author_id():
        op.drop_column("post", "author_id")
