"""Add a standalone directory for synthetic manual-selection demos."""
import sqlalchemy as sa
from alembic import op

revision = "0009_demo_directory"
down_revision = "0008_reference_face_gallery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "demodirectoryprofile",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("bio", sa.String(), nullable=False),
        sa.Column("image_alt", sa.String(), nullable=False),
        sa.Column("image_source", sa.String(), nullable=False),
        sa.Column("image_prompt", sa.String(), nullable=False),
        sa.Column("image_png", sa.LargeBinary(), nullable=False),
        sa.Column("case_history", sa.JSON(), nullable=False),
    )
    op.create_index("ix_demodirectoryprofile_full_name", "demodirectoryprofile", ["full_name"])


def downgrade():
    op.drop_table("demodirectoryprofile")
