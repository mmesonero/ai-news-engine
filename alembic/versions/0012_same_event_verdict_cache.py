"""cache LLM same-event verdicts to stop re-judging borderline pairs

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-20

The cluster merger asks the LLM "same event?" for every borderline cluster pair
in a 14-day window on every run (4×/day). The verdict for a fixed pair of
articles never changes, so this table memoizes it keyed by the ordered
raw_content id pair. Rows cascade-delete with their raw_content so retention
prunes the cache for free.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "same_event_verdicts",
        sa.Column("raw_low_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_high_id", sa.BigInteger(), nullable=False),
        sa.Column("same_event", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["raw_low_id"], ["raw_content.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_high_id"], ["raw_content.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("raw_low_id", "raw_high_id"),
    )


def downgrade() -> None:
    op.drop_table("same_event_verdicts")
