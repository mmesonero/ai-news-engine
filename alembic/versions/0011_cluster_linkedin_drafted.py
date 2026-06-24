"""track when a cluster was turned into a LinkedIn breaking draft

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-24

Lets the breaking-news LinkedIn drafter pick each story only once (NULL = eligible),
so the two daily pipeline runs never re-draft the same story.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_clusters",
        sa.Column("linkedin_drafted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_clusters", "linkedin_drafted_at")
