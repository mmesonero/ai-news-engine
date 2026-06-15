from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.news import NewsItem


class ClusterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cluster_topic: str | None
    representative_content_id: int | None
    member_count: int
    created_at: datetime


class ClusterDetail(ClusterRead):
    representative: NewsItem | None
    members: list[NewsItem]


class TrendingItem(BaseModel):
    cluster_id: int
    cluster_topic: str | None
    member_count: int
    distinct_sources: int = 1   # confirmation-bias signal: how many different outlets covered it
    importance_score: int | None
    boosted_score: int | None = None  # importance + cross-source boost (for display)
    representative: NewsItem | None
