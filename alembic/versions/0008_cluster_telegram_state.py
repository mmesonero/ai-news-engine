"""track Telegram message id + sent source count on clusters

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-16

Lets us EDIT an already-sent Telegram post when a later duplicate raises the
cross-source count (and thus the boosted score).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_clusters", sa.Column("telegram_message_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "content_clusters",
        sa.Column("telegram_sources", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("content_clusters", "telegram_sources")
    op.drop_column("content_clusters", "telegram_message_id")
