from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database import Base


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raw_content_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("raw_content.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
