"""index raw_content.fetched_at + partial index over un-pruned rows

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-25

fetched_at is filtered in nearly every query (retention, dedup nearest_within join,
cluster_merger, telegram, trending, weekly_top, stats, static_site) but had no
index — sequential scans worsen as the permanent archive grows. Add a plain index
on fetched_at, plus a partial index restricted to live (un-pruned) rows to keep the
embed-pending / retention scans bounded as pruned rows accumulate.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_raw_content_fetched_at", "raw_content", ["fetched_at"])
    op.create_index(
        "ix_raw_content_unpruned",
        "raw_content",
        ["fetched_at"],
        postgresql_where=sa.text("embedding_pruned = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_raw_content_unpruned", table_name="raw_content")
    op.drop_index("ix_raw_content_fetched_at", table_name="raw_content")
