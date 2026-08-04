"""Baseline schema — every table SENTINEL stores.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-04

This consolidates the entire schema into one authoritative starting point.

It replaces an earlier three-revision chain that could not build a database at
all: its initial revision was an empty `pass`, so the follow-ups tried to add
columns to a `post` table nothing had created. The schema everyone was actually
running came from `SQLModel.metadata.create_all()` at boot, which meant the
migration history described a database that never existed.

Existing databases are stamped with this revision rather than having it run
against them (see `app/database.py`) — their tables already match, because both
this file and create_all() are generated from the same models.

The eight tables, and what is lost if one is not durable:

  post           every collected post, de-duplicated on content_hash. The corpus.
  alert          raised threats and their workflow state.
  watchlistitem  the terms steering the crawlers.
  report         generated incident/escalation reports and their PDF paths.
  suspect        registry records: identity, charges, handles, face templates.
  auditlog       who did what, when, from where. Append-only (see 0002).
  facesearchlog  every biometric query run. Append-only (see 0002).
  user           officer accounts, scrypt hashes, lockout and revocation state.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "post",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("content_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("author_handle", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("author_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("author_followers", sa.Integer(), nullable=False),
        sa.Column("author_verified", sa.Boolean(), nullable=False),
        sa.Column("author_account_age_days", sa.Integer(), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("translation", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("language", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("code_mixed", sa.Boolean(), nullable=False),
        sa.Column("sentiment_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=False),
        sa.Column("sentiment_consensus", sa.JSON(), nullable=True),
        sa.Column("intent", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("threat_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("threat_confidence", sa.Float(), nullable=False),
        sa.Column("class_probs", sa.JSON(), nullable=True),
        sa.Column("hate_flags", sa.JSON(), nullable=True),
        sa.Column("toxicity_score", sa.Float(), nullable=False),
        sa.Column("threat_score", sa.Float(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("hashtags", sa.JSON(), nullable=True),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("engagement", sa.JSON(), nullable=True),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("media_urls", sa.JSON(), nullable=True),
        sa.Column("cluster_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_amplified", sa.Boolean(), nullable=False),
        sa.Column("llm_verification", sa.JSON(), nullable=True),
        sa.Column("fact_check", sa.JSON(), nullable=True),
        sa.Column("evidence_report", sa.JSON(), nullable=True),
        sa.Column("true_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # content_hash is UNIQUE: re-collecting a post the crawlers have already
    # seen must be a no-op, not a duplicate row. This is what makes the corpus
    # accumulate cleanly instead of growing a copy per crawl cycle.
    op.create_index("ix_post_content_hash", "post", ["content_hash"], unique=True)
    for column in ("author_handle", "cluster_id", "created_at", "language",
                   "location", "platform", "threat_label", "threat_score"):
        op.create_index(f"ix_post_{column}", "post", [column], unique=False)

    op.create_table(
        "alert",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("post_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("severity", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("threat_score", sa.Float(), nullable=False),
        sa.Column("escalation", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("created_at", "post_id", "severity", "status"):
        op.create_index(f"ix_alert_{column}", "alert", [column], unique=False)

    op.create_table(
        "watchlistitem",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("priority", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("kind", "priority"):
        op.create_index(f"ix_watchlistitem_{column}", "watchlistitem", [column], unique=False)

    op.create_table(
        "report",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("period_hours", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("pdf_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_created_at", "report", ["created_at"], unique=False)

    op.create_table(
        "suspect",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("record_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("risk_level", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("case_ids", sa.JSON(), nullable=True),
        sa.Column("charges", sa.JSON(), nullable=True),
        sa.Column("convictions", sa.Integer(), nullable=False),
        sa.Column("jurisdiction", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("last_known_location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("wanted_since", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("gender", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("nationality", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("identifying_marks", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("social_handles", sa.JSON(), nullable=True),
        # Biometric templates. Encrypted at rest when BIOMETRIC_ENCRYPTION_KEY
        # is set; the column itself is opaque either way.
        sa.Column("face_templates", sa.JSON(), nullable=True),
        sa.Column("photo_thumb", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("created_at", "full_name", "last_known_location",
                   "record_type", "risk_level", "status"):
        op.create_index(f"ix_suspect_{column}", "suspect", [column], unique=False)

    op.create_table(
        "user",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("username", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("badge_number", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("unit", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("password_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_ip", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # "user" is a reserved word in Postgres. SQLAlchemy quotes it automatically
    # in the DDL and in every query it generates, so the table works — but hand
    # written SQL against this database must spell it "user", with the quotes.
    op.create_index("ix_user_username", "user", ["username"], unique=True)
    for column in ("active", "created_at", "role"):
        op.create_index(f"ix_user_{column}", "user", [column], unique=False)

    op.create_table(
        "auditlog",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("action", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        # Actor fields are denormalised on purpose: copied in at write time so
        # the record still reads correctly after the account is renamed,
        # demoted or deactivated. That is why there is no foreign key here.
        sa.Column("actor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("actor_username", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("actor_role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("actor_badge", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ip", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_agent", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("action", "actor_id", "actor_username", "created_at"):
        op.create_index(f"ix_auditlog_{column}", "auditlog", [column], unique=False)

    op.create_table(
        "facesearchlog",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("image_sha256", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("faces_detected", sa.Integer(), nullable=False),
        sa.Column("identified_count", sa.Integer(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("created_at", "image_sha256"):
        op.create_index(f"ix_facesearchlog_{column}", "facesearchlog", [column], unique=False)


def downgrade() -> None:
    # Dropping the tables drops their indexes with them on both dialects.
    for table in ("facesearchlog", "auditlog", "user", "suspect", "report",
                  "watchlistitem", "alert", "post"):
        op.drop_table(table)
