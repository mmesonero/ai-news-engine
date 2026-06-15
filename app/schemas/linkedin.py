from __future__ import annotations

from pydantic import BaseModel

from app.schemas.news import NewsItem


class LinkedinAngles(BaseModel):
    hooks: list[str] = []
    angles: list[str] = []
    controversial_points: list[str] = []
    business_implications: list[str] = []
    future_predictions: list[str] = []


class LinkedinIdea(BaseModel):
    content_id: int
    cluster_id: int | None
    linkedin_potential_score: int | None
    angles: LinkedinAngles
    source: NewsItem
