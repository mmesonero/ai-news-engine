from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RawContentDraft(BaseModel):
    """In-memory record produced by an ingestor before it lands in Postgres."""

    external_id: str | None
    title: str
    url: str
    author: str | None = None
    raw_text: str
    published_at: datetime | None = None
    language: str | None = "en"
    metadata: dict[str, Any] = {}


class ProcessedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cleaned_summary: str | None
    key_topics: list[str]
    novelty_score: int | None
    importance_score: int | None
    linkedin_potential_score: int | None
    business_impact_score: int | None
    ai_generated_insights: dict[str, Any]
    linkedin_angles: dict[str, Any]
    is_noise: bool
    theme: str | None = None
    importance_tier: str | None = None


class NewsItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    title: str
    url: str
    author: str | None
    published_at: datetime | None
    cluster_id: int | None = None
    member_count: int | None = None
    distinct_sources: int | None = None
    processed: ProcessedRead | None = None


class NewsList(BaseModel):
    items: list[NewsItem]
    next_cursor: str | None = None
