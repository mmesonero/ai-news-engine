from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.cluster import ContentCluster
from app.models.embedding import Embedding
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.models.source import Source

router = APIRouter()


class Stats(BaseModel):
    sources_total: int
    sources_active: int
    raw_content_total: int
    raw_content_last_24h: int
    embeddings_total: int
    clusters_total: int
    unique_news: int           # clusters whose representative is not noise
    duplicates: int            # raw - (unique_news + noise + unprocessed)
    processed_total: int
    noise_total: int
    noise_rate: float


@router.get("/stats", response_model=Stats)
async def stats(session: AsyncSession = Depends(db_session)) -> Stats:
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    sources_total = (await session.execute(select(func.count(Source.id)))).scalar_one()
    sources_active = (
        await session.execute(select(func.count(Source.id)).where(Source.active.is_(True)))
    ).scalar_one()
    raw_total = (await session.execute(select(func.count(RawContent.id)))).scalar_one()
    raw_24h = (
        await session.execute(
            select(func.count(RawContent.id)).where(
                or_(
                    RawContent.published_at >= since_24h,
                    (RawContent.published_at.is_(None))
                    & (RawContent.fetched_at >= since_24h),
                )
            )
        )
    ).scalar_one()
    embeddings_total = (await session.execute(select(func.count(Embedding.id)))).scalar_one()
    clusters_total = (await session.execute(select(func.count(ContentCluster.id)))).scalar_one()
    processed_total = (await session.execute(select(func.count(ProcessedContent.id)))).scalar_one()
    noise_total = (
        await session.execute(
            select(func.count(ProcessedContent.id)).where(ProcessedContent.is_noise.is_(True))
        )
    ).scalar_one()

    # Unique news = number of clusters whose representative survived noise filtering.
    # Clusters without a representative yet are excluded (still in pipeline).
    unique_q = (
        select(func.count(ContentCluster.id))
        .outerjoin(
            ProcessedContent,
            ProcessedContent.raw_content_id == ContentCluster.representative_content_id,
        )
        .where(
            ContentCluster.representative_content_id.is_not(None),
            (ProcessedContent.is_noise.is_(False)) | (ProcessedContent.id.is_(None)),
        )
    )
    unique_news = int((await session.execute(unique_q)).scalar_one())

    duplicates = max(0, int(raw_total) - unique_news - int(noise_total))
    noise_rate = float(noise_total) / float(processed_total) if processed_total else 0.0

    return Stats(
        sources_total=int(sources_total),
        sources_active=int(sources_active),
        raw_content_total=int(raw_total),
        raw_content_last_24h=int(raw_24h),
        embeddings_total=int(embeddings_total),
        clusters_total=int(clusters_total),
        unique_news=unique_news,
        duplicates=duplicates,
        processed_total=int(processed_total),
        noise_total=int(noise_total),
        noise_rate=round(noise_rate, 4),
    )
