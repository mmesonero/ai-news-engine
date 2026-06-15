"""add group_name to sources

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-30

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("group_name", sa.Text, nullable=True))
    op.create_index("ix_sources_group_name", "sources", ["group_name"])

    # Backfill: group related sources together.
    op.execute(
        """
        UPDATE sources SET group_name = 'Anthropic'
        WHERE name IN ('Anthropic', 'Anthropic (Claude)', 'Anthropic News');
        UPDATE sources SET group_name = 'TechCrunch'
        WHERE name IN ('TechCrunch', 'TechCrunch AI');
        UPDATE sources SET group_name = 'The Verge'
        WHERE name IN ('The Verge', 'The Verge AI');
        """
    )


def downgrade() -> None:
    op.drop_index("ix_sources_group_name", table_name="sources")
    op.drop_column("sources", "group_name")
