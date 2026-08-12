"""Add suspect.height_cm and suspect.occupation.

The registry's physical/demographic descriptors (gender, age, nationality,
identifying_marks) had no field for stature or livelihood, both of which the
Identified Individuals panel on the forensics tool renders as columns
alongside age and gender. Additive; nothing needs backfilling — a record
enrolled before this column existed simply has no height/occupation on file,
which the UI already renders as an empty/absent field.

Idempotent in the same way as 0006: offline mode (`alembic upgrade --sql`)
has no live connection to check with, so it always emits the ALTER and leaves
the already-exists judgement to whoever reviews the script before running it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 — see alembic/script.py.mako
from alembic import op

revision: str = "0007_suspect_height_occupation"
down_revision: Union[str, Sequence[str], None] = "0006_report_xlsx_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    if op.get_context().as_sql:
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("suspect")}


def upgrade() -> None:
    cols = _existing_columns()
    if op.get_context().as_sql or "height_cm" not in cols:
        op.add_column(
            "suspect",
            sa.Column("height_cm", sa.Integer(), nullable=False, server_default="0"),
        )
    if op.get_context().as_sql or "occupation" not in cols:
        op.add_column(
            "suspect",
            sa.Column("occupation", sqlmodel.sql.sqltypes.AutoString(),
                      nullable=False, server_default=""),
        )


def downgrade() -> None:
    cols = _existing_columns()
    if op.get_context().as_sql or "occupation" in cols:
        op.drop_column("suspect", "occupation")
    if op.get_context().as_sql or "height_cm" in cols:
        op.drop_column("suspect", "height_cm")
