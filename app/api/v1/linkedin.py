from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.cluster import ClusterItem
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.schemas.linkedin import LinkedinAngles, LinkedinIdea
from app.schemas.news import NewsItem, ProcessedRead

router = APIRouter()


@router.get("/linkedin-ideas", response_model=list[LinkedinIdea])
async def linkedin_ideas(
    session: AsyncSession = Depends(db_session),
    limit: int = Query(default=25, ge=1, le=200),
    min_score: int = Query(default=60, ge=0, le=100),
    source_id: int | None = Query(default=None),
) -> list[LinkedinIdea]:
    stmt = (
        select(ProcessedContent, RawContent, ClusterItem.cluster_id)
        .join(RawContent, RawContent.id == ProcessedContent.raw_content_id)
        .outerjoin(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
        .where(
            (ProcessedContent.is_noise.is_(False))
            & (ProcessedContent.linkedin_potential_score >= min_score)
        )
        .order_by(desc(ProcessedContent.linkedin_potential_score))
        .limit(limit)
    )
    if source_id is not None:
        stmt = stmt.where(RawContent.source_id == source_id)
    res = await session.execute(stmt)
    ideas: list[LinkedinIdea] = []
    for proc, raw, cluster_id in res.all():
        angles = LinkedinAngles(**(proc.linkedin_angles or {}))
        source_item = NewsItem(
            id=raw.id,
            source_id=raw.source_id,
            title=raw.title,
            url=raw.url,
            author=raw.author,
            published_at=raw.published_at,
            cluster_id=int(cluster_id) if cluster_id is not None else None,
            processed=ProcessedRead.model_validate(proc),
        )
        ideas.append(
            LinkedinIdea(
                content_id=raw.id,
                cluster_id=int(cluster_id) if cluster_id is not None else None,
                linkedin_potential_score=proc.linkedin_potential_score,
                angles=angles,
                source=source_item,
            )
        )
    return ideas
