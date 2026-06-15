from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProcessedContent(Base):
    __tablename__ = "processed_content"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raw_content_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("raw_content.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    cleaned_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_topics: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    novelty_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    importance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linkedin_potential_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_impact_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_generated_insights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    linkedin_angles: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_noise: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    theme: Mapped[str | None] = mapped_column(Text, nullable=True)
    importance_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
