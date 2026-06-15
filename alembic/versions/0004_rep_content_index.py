"""index content_clusters.representative_content_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-15

representative_content_id is joined in trending/weekly-top/stats/briefing and
used in IN-subqueries, but had no index. Add one.
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_content_clusters_representative",
        "content_clusters",
        ["representative_content_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_clusters_representative", table_name="content_clusters")
