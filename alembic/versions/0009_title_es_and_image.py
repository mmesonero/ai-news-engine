"""add processed_content.title_es + raw_content.image_url

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-16

Spanish display title (enrichment) + article image (og:image / thumbnail) for
the web hero and Telegram photo.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processed_content", sa.Column("title_es", sa.Text(), nullable=True))
    op.add_column("raw_content", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_content", "image_url")
    op.drop_column("processed_content", "title_es")
