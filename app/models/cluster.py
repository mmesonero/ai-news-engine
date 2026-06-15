from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Text, func
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
