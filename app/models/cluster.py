from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ContentCluster(Base):
    __tablename__ = "content_clusters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cluster_topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    representative_content_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("raw_content.id", ondelete="SET NULL"),
        nullable=True,
    )
    # When this story was delivered to Telegram. NULL = not yet sent → eligible.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Telegram message id of the sent post + the source count at send/edit time,
    # so a later duplicate can edit the post to bump the counter + boosted score.
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_sources: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # When this story was turned into a LinkedIn breaking DRAFT. NULL = eligible
    # (each story is drafted at most once, across both daily runs).
    linkedin_drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClusterItem(Base):
    __tablename__ = "cluster_items"

    cluster_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("content_clusters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    raw_content_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("raw_content.id", ondelete="CASCADE"),
        primary_key=True,
    )
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
