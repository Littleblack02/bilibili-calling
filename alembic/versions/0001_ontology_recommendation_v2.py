"""Add the non-destructive Ontology/Recommendation V2 schema.

Revision ID: 0001_v2
Revises: None
Create Date: 2026-07-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.models import Base


revision = "0001_v2"
down_revision = None
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    # This adoption revision creates every missing table on an empty install,
    # while checkfirst prevents replacement of existing user tables.
    Base.metadata.create_all(bind=bind, checkfirst=True)

    if "profile_features" not in _columns(bind, "user_interest_profiles"):
        with op.batch_alter_table("user_interest_profiles") as batch:
            batch.add_column(sa.Column("profile_features", sa.JSON(), nullable=True))

    if "last_seen_sync_id" not in _columns(bind, "user_content_signals"):
        with op.batch_alter_table("user_content_signals") as batch:
            batch.add_column(sa.Column("last_seen_sync_id", sa.String(length=64), nullable=True))
            batch.create_index("ix_user_content_signals_last_seen_sync_id", ["last_seen_sync_id"], unique=False)


def downgrade() -> None:
    raise RuntimeError(
        "0001_v2 is intentionally irreversible; restore a pre-migration backup if required"
    )
