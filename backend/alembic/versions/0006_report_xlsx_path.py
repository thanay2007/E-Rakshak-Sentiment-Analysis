"""Add report.xlsx_path — the Excel rendering alongside the PDF.

Reports have always been rendered twice from one payload: a JSON blob for the
UI and a styled PDF for the file. Analysts asked for the same content as a
workbook, because a PDF is where numbers go to stop being numbers — the top
threats cannot be sorted, filtered or pasted into a case file from it.

Additive and nothing needs backfilling. A report generated before this column
existed has no workbook on disk, so "" is not a missing value to repair; it is
the correct answer, and the download endpoint 404s on it exactly as it already
does for a report whose PDF never rendered.

Idempotent in the same way as 0003 and 0004 — a database adopted from the
pre-migration era may already have been ALTER-ed by hand, and `ADD COLUMN` on
an existing name is a hard error on every backend. That check needs a live
connection to inspect, which `alembic upgrade --sql` does not have, so offline
mode emits the unguarded ALTER and leaves the already-exists judgement to
whoever reviews the script before running it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 — see alembic/script.py.mako
from alembic import op

revision: str = "0006_report_xlsx_path"
# Renumbered on merge. This was authored against 0004 in parallel with
# 0005_sentiment_taxonomy, which left the tree with two heads off the same
# parent. The two touch different tables and neither had been applied
# anywhere, so the fork was resolved by ordering rather than by a merge
# revision.
down_revision: Union[str, Sequence[str], None] = "0005_sentiment_taxonomy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_xlsx_path() -> bool:
    """True when the column is already there. Offline (`--sql`) mode has no
    connection to ask — `as_sql` is how the MigrationContext reports that —
    so it answers False and the ALTER always renders."""
    if op.get_context().as_sql:
        return False
    return "xlsx_path" in {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("report")
    }


def upgrade() -> None:
    if not _has_xlsx_path():
        op.add_column(
            "report",
            sa.Column("xlsx_path", sqlmodel.sql.sqltypes.AutoString(),
                      nullable=False, server_default=""),
        )


def downgrade() -> None:
    if op.get_context().as_sql or _has_xlsx_path():
        op.drop_column("report", "xlsx_path")
