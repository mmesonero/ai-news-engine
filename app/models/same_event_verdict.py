from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SameEventVerdict(Base):
    """Memoized result of the LLM "are these two items the same event?" judge.

    The cluster merger re-derives the same borderline pairs on every run over a
    14-day window, so without a cache it re-asks the LLM the same question 4×/day
    for two weeks. The verdict for a fixed pair of articles is stable, so we store
    it keyed by the ORDERED raw_content id pair (low, high) and skip re-judging.

    Rows cascade-delete with their raw_content, so retention cleanup prunes the
    cache automatically — no separate maintenance.
    """

    __tablename__ = "same_event_verdicts"

    raw_low_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("raw_content.id", ondelete="CASCADE"),
        primary_key=True,
    )
    raw_high_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("raw_content.id", ondelete="CASCADE"),
        primary_key=True,
    )
    same_event: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
