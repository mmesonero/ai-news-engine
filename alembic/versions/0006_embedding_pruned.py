"""add raw_content.embedding_pruned (storage saver)

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-15

After dedup, non-representative cluster members keep their row (so cross-source
counts still work) but their heavy embedding + raw_text are dropped. This flag
stops embed_pending from re-embedding them on the next run.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_content",
        sa.Column(
            "embedding_pruned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("raw_content", "embedding_pruned")
