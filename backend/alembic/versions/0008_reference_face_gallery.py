"""Add the reference face gallery table (known persons, not records).

The `pics/` folder is a drop point; this table is where a reference photo
actually lives once it has been read — the sealed 128-d embedding, a face crop
and a downscaled copy of the photo. Keeping it in the database rather than the
checkout is the point: the enrolled person then survives the file being
deleted, the repo being re-cloned, or a second console running against the same
Supabase project, and no biometric material sits in the source tree.

Deliberately a separate table from `suspect`. A Suspect row asserts a criminal
record and a hit against one opens a dossier; a row here asserts only what a
person looks like. Merging them would mean every named face arrived dressed as
a police record.

Additive and idempotent: nothing else reads or writes this table, and a
deployment that already created it through SQLModel's create_all is left alone.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 — see alembic/script.py.mako
from alembic import op

revision: str = "0008_reference_face_gallery"
down_revision: Union[str, Sequence[str], None] = "0007_suspect_height_occupation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "referenceface"


def _exists() -> bool:
    if op.get_context().as_sql:
        return False
    return _TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _exists():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("person_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("person_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("image_sha256", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("source_file", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default="gallery_folder"),
        # Sealed with BIOMETRIC_ENCRYPTION_KEY (security/crypto.py). Text rather
        # than bytea so the column behaves identically on SQLite and Postgres.
        sa.Column("encoding_enc", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("thumb_enc", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("image_enc", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("quality", sa.JSON(), nullable=True),
        sa.Column("other_faces_ignored", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f(f"ix_{_TABLE}_person_name"), _TABLE, ["person_name"])
    op.create_index(op.f(f"ix_{_TABLE}_person_key"), _TABLE, ["person_key"])
    # The ingestion dedupe key: re-dropping a photo already in the gallery must
    # find it by content hash rather than enrol a second copy of the same face.
    op.create_index(op.f(f"ix_{_TABLE}_image_sha256"), _TABLE, ["image_sha256"])
    op.create_index(op.f(f"ix_{_TABLE}_created_at"), _TABLE, ["created_at"])


def downgrade() -> None:
    op.drop_table(_TABLE)
