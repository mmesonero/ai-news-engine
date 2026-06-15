from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.schemas.cluster import TrendingItem
from app.schemas.news import NewsItem, ProcessedRead

router = APIRouter()


@router.get("/trending", response_model=list[TrendingItem])
async def trending(
    session: AsyncSession = Depends(db_session),
    window_hours: int = Query(default=72, ge=1, le=720),
    limit: int = Query(default=20, ge=1, le=200),
    source_id: int | None = Query(default=None),
) -> list[TrendingItem]:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    member_count = func.count(ClusterItem.raw_content_id).label("member_count")
    distinct_sources = func.count(func.distinct(RawContent.source_id)).label("distinct_sources")
    importance = func.coalesce(ProcessedContent.importance_score, 0).label("importance")
    boost = func.least(20, (distinct_sources - 1) * 8).label("boost")
    boosted = (importance + boost).label("boosted")

    stmt = (
        select(
            ContentCluster.id,
            ContentCluster.cluster_topic,
            ContentCluster.representative_content_id,
            member_count,
            distinct_sources,
            importance,
            boosted,
        )
        .join(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
        .join(RawContent, RawContent.id == ClusterItem.raw_content_id)
        .outerjoin(
            ProcessedContent,
            ProcessedContent.raw_content_id == ContentCluster.representative_content_id,
        )
        # Use publication date when present; fall back to fetched_at only when
        # the source didn't expose a published_at. This stops month-old articles
        # from polluting "last 72h" just because we ingested them recently.
        .where(
            or_(
                RawContent.published_at >= since,
                (RawContent.published_at.is_(None)) & (RawContent.fetched_at >= since),
            )
        )
    )
    if source_id is not None:
        # Filter clusters whose members include this source.
        stmt = stmt.where(RawContent.source_id == source_id)
    stmt = (
        stmt
        .group_by(ContentCluster.id, ProcessedContent.importance_score)
        .order_by(desc(boosted * member_count), desc(member_count))
        .limit(limit)
    )
    res = await session.execute(stmt)
    out: list[TrendingItem] = []
    for cid, topic, rep_id, count, sources, score, boosted_val in res.all():
        rep_item: NewsItem | None = None
        if rep_id is not None:
            rep_q = await session.execute(
                select(RawContent, ProcessedContent)
                .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
                .where(RawContent.id == rep_id)
            )
            row = rep_q.first()
            if row is not None:
                raw, proc = row
                rep_item = NewsItem(
                    id=raw.id,
                    source_id=raw.source_id,
                    title=raw.title,
                    url=raw.url,
                    author=raw.author,
                    published_at=raw.published_at,
                    cluster_id=int(cid),
                    processed=ProcessedRead.model_validate(proc) if proc else None,
                )
        out.append(
            TrendingItem(
                cluster_id=int(cid),
                cluster_topic=topic,
                member_count=int(count),
                distinct_sources=int(sources),
                importance_score=int(score) if score is not None else None,
                boosted_score=int(boosted_val) if boosted_val is not None else None,
                representative=rep_item,
            )
        )
    return out
