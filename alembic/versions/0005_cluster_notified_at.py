"""add notified_at to content_clusters (Telegram per-story delivery)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-15

Tracks which stories were already sent to Telegram so each new story is
delivered exactly once across runs.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_clusters",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill: mark all EXISTING clusters as already-notified so enabling
    # per-story Telegram doesn't dump the whole backlog on first run.
    op.execute("UPDATE content_clusters SET notified_at = NOW() WHERE notified_at IS NULL")
    op.create_index(
        "ix_content_clusters_notified_at", "content_clusters", ["notified_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_content_clusters_notified_at", table_name="content_clusters")
    op.drop_column("content_clusters", "notified_at")
