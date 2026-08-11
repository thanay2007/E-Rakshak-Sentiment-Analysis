"""Retire the threat taxonomy — posts carry a sentiment tag and a concern score.

Revision ID: 0005_sentiment_taxonomy
Revises: 0004_post_author_id
Create Date: 2026-08-10

The model used to emit one of four categories — "Incitement to Violence",
"Inflammatory", "Fake News", "Neutral" — alongside sentiment. Those are
investigative conclusions about the world, not properties of a post's text, and
a sentiment model has no basis for asserting either. They are gone. What each
post carries now is the judgement the models can defend:

    sentiment_label       positive | negative | neutral   (already existed)
    sentiment_confidence  was threat_confidence
    concern_score         was threat_score — 0-100, now derived from negativity
                          × confidence, toxicity, reach and matched-term severity
                          (app/ml/score.py)

`post.threat_label` is dropped outright rather than kept for history: every
value in it is a claim this system no longer makes, and leaving the column
would let a report or an export keep printing it. `class_probs` survives with
the same name and a new meaning — the ensemble's averaged probability over the
three sentiment labels instead of over four categories.

`alert.threat_score` becomes `alert.concern_score` for the same reason; the
alert bands are unchanged, only what feeds them.

Mechanics. SQLite has supported RENAME COLUMN since 3.25 and DROP COLUMN since
3.35, and Postgres has always had both, so plain ALTERs work on either backend
with no table rebuild. RENAME COLUMN carries an index over to the new name but
keeps the old index NAME, so each renamed column's index is dropped first and
recreated under the matching name — leaving `ix_post_threat_score` pointing at
`concern_score` would be a trap for the next person reading the schema.

The assistant's read-only views (app/services/assistant/sandbox.py) SELECT these
columns by name, and Postgres refuses to drop a column a view depends on. The
views are therefore dropped first and left dropped: `ensure_views()` recreates
them from `_VIEW_SQL` at the next boot, which is where their definition lives,
so re-creating them here would mean maintaining that SQL in two places and
would freeze this migration's copy the moment the view changes again.

Guarded the same way 0004 is: a database may already have been altered by hand,
and `alembic upgrade --sql` has no connection to inspect, so offline mode
renders the unguarded statements and leaves the judgement to the reviewer.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 — see alembic/script.py.mako
from alembic import op

revision: str = "0005_sentiment_taxonomy"
down_revision: Union[str, Sequence[str], None] = "0004_post_author_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    """Column names on `table`, or an empty set in offline (--sql) mode where
    there is no connection to inspect."""
    if op.get_context().as_sql:
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _rename(table: str, old: str, new: str, *, indexed: bool) -> None:
    cols = _columns(table)
    # offline mode reports no columns; render the ALTER unconditionally there
    if cols and (old not in cols or new in cols):
        return
    if indexed:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_{old}")
    op.alter_column(table, old, new_column_name=new)
    if indexed:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{new} ON {table} ({new})")


#: Recreated at boot by app.services.assistant.sandbox.ensure_views().
_ASSISTANT_VIEWS = ("assistant_posts", "assistant_alerts", "assistant_watchlist")


def _drop_assistant_views() -> None:
    for name in _ASSISTANT_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {name}")


def upgrade() -> None:
    _drop_assistant_views()
    _rename("post", "threat_confidence", "sentiment_confidence", indexed=False)
    _rename("post", "threat_score", "concern_score", indexed=True)
    _rename("alert", "threat_score", "concern_score", indexed=False)

    cols = _columns("post")
    if not cols or "threat_label" in cols:
        op.execute("DROP INDEX IF EXISTS ix_post_threat_label")
        op.drop_column("post", "threat_label")

    # sentiment_label is the tag now, so it is what the feed filters and the
    # trend group-bys hit. It has been unindexed since the baseline because
    # nothing queried on it.
    op.execute("CREATE INDEX IF NOT EXISTS ix_post_sentiment_label "
               "ON post (sentiment_label)")


def downgrade() -> None:
    _drop_assistant_views()
    op.execute("DROP INDEX IF EXISTS ix_post_sentiment_label")
    cols = _columns("post")
    if not cols or "threat_label" not in cols:
        op.add_column(
            "post",
            sa.Column("threat_label", sqlmodel.sql.sqltypes.AutoString(),
                      nullable=False, server_default="Neutral"),
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_post_threat_label ON post (threat_label)")

    _rename("alert", "concern_score", "threat_score", indexed=False)
    _rename("post", "concern_score", "threat_score", indexed=True)
    _rename("post", "sentiment_confidence", "threat_confidence", indexed=False)
