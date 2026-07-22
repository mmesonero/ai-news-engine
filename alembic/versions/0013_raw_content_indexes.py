"""index raw_content.fetched_at + partial index over un-pruned rows

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-25

Renumbered 0012 -> 0013 when the hardening branch merged into main: both
lineages had independently added a 0012, leaving alembic with two heads.
same_event_verdict_cache keeps 0012 because production already applied it.

fetched_at is filtered in nearly every query (retention, dedup nearest_within join,
cluster_merger, telegram, trending, weekly_top, stats, static_site) but had no
index — sequential scans worsen as the permanent archive grows. Add a plain index
on fetched_at, plus a partial index restricted to live (un-pruned) rows to keep the
embed-pending / retention scans bounded as pruned rows accumulate.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
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
