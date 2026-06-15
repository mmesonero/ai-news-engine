"""Weekly top news — composite-scored with cross-source confirmation bias.

The composite favours stories that multiple outlets independently covered:
that's the strongest signal that something actually matters in the industry.

  composite = importance + min(20, (distinct_sources - 1) * 8)
            + 0.3 * linkedin_potential
            + 5 * member_count

Items capped to representative-per-cluster, restricted to recent publish dates.
"""
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

MAX_BOOST = 20            # cap on confirmation-bias bonus
PER_SOURCE_BOOST = 8      # +8 per extra outlet (capped by MAX_BOOST)


@router.get("/weekly-top", response_model=list[TrendingItem])
async def weekly_top(
    session: AsyncSession = Depends(db_session),
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=10, ge=1, le=20),
    min_importance: int = Query(default=60, ge=0, le=100),
) -> list[TrendingItem]:
    """Top stories of last `days` days, ranked by importance + cross-source confirmation."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    member_count = func.count(ClusterItem.raw_content_id).label("member_count")
    distinct_sources = func.count(func.distinct(RawContent.source_id)).label("distinct_sources")
    importance = func.coalesce(ProcessedContent.importance_score, 0).label("importance")
    linkedin = func.coalesce(ProcessedContent.linkedin_potential_score, 0).label("linkedin")

    # Compute the cross-source boost in SQL: min(MAX_BOOST, (distinct_sources-1)*PER_SOURCE_BOOST)
    boost = func.least(MAX_BOOST, (distinct_sources - 1) * PER_SOURCE_BOOST).label("boost")
    boosted = (importance + boost).label("boosted")
    composite = (boosted + linkedin * 0.3 + member_count * 5).label("composite")

    stmt = (
        select(
            ContentCluster.id,
            ContentCluster.cluster_topic,
            ContentCluster.representative_content_id,
            member_count,
            distinct_sources,
            importance,
            boosted,
            composite,
        )
        .join(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
        .join(RawContent, RawContent.id == ClusterItem.raw_content_id)
        .outerjoin(
            ProcessedContent,
            ProcessedContent.raw_content_id == ContentCluster.representative_content_id,
        )
        .where(ProcessedContent.is_noise.is_(False))
        .where(
            or_(
                RawContent.published_at >= since,
                (RawContent.published_at.is_(None)) & (RawContent.fetched_at >= since),
            )
        )
        .where(func.coalesce(ProcessedContent.importance_score, 0) >= min_importance)
        .group_by(
            ContentCluster.id,
            ProcessedContent.importance_score,
            ProcessedContent.linkedin_potential_score,
        )
        .order_by(desc(composite))
        .limit(limit)
    )
    res = await session.execute(stmt)
    out: list[TrendingItem] = []
    for cid, topic, rep_id, count, sources, imp, boosted_val, _composite in res.all():
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
                    id=raw.id, source_id=raw.source_id, title=raw.title,
                    url=raw.url, author=raw.author, published_at=raw.published_at,
                    cluster_id=int(cid),
                    processed=ProcessedRead.model_validate(proc) if proc else None,
                )
        out.append(TrendingItem(
            cluster_id=int(cid),
            cluster_topic=topic,
            member_count=int(count),
            distinct_sources=int(sources),
            importance_score=int(imp) if imp is not None else None,
            boosted_score=int(boosted_val) if boosted_val is not None else None,
            representative=rep_item,
        ))
    return out
