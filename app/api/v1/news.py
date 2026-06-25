from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.database import SessionLocal
from app.logging_config import get_logger
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.schemas.news import NewsItem, NewsList, ProcessedRead
from app.services.enrichment_service import EnrichmentService

router = APIRouter()
log = get_logger(__name__)


def _to_news_item(
    raw: RawContent, processed: ProcessedContent | None, cluster_id: int | None
) -> NewsItem:
    return NewsItem(
        id=raw.id,
        source_id=raw.source_id,
        title=raw.title,
        url=raw.url,
        author=raw.author,
        published_at=raw.published_at,
        cluster_id=cluster_id,
        processed=ProcessedRead.model_validate(processed) if processed is not None else None,
    )


@router.get("/news", response_model=NewsList)
async def list_news(
    session: AsyncSession = Depends(db_session),
    topic: str | None = Query(default=None),
    min_importance: int = Query(default=0, ge=0, le=100),
    since: datetime | None = Query(default=None),
    include_duplicates: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=100),
) -> NewsList:
    """Returns cluster representatives by default (deduped). Set ?include_duplicates=true
    to see every article."""
    stmt = (
        select(RawContent, ProcessedContent, ClusterItem.cluster_id)
        .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .outerjoin(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
        .where((ProcessedContent.is_noise.is_(False)) | (ProcessedContent.id.is_(None)))
        .order_by(desc(RawContent.published_at), desc(RawContent.id))
        .limit(limit)
    )

    if not include_duplicates:
        # Keep only rows that are the representative of their cluster (or have no cluster yet).
        rep_subq = select(ContentCluster.representative_content_id)
        stmt = stmt.where(
            (ClusterItem.cluster_id.is_(None))
            | (RawContent.id.in_(rep_subq))
        )

    if min_importance > 0:
        stmt = stmt.where(ProcessedContent.importance_score >= min_importance)
    if since is not None:
        stmt = stmt.where(RawContent.published_at >= since)
    if topic:
        # Naive contains; key_topics is JSON array.
        stmt = stmt.where(ProcessedContent.key_topics.contains([topic.lower()]))

    res = await session.execute(stmt)
    items: list[NewsItem] = []
    for raw, proc, cluster_id in res.all():
        items.append(_to_news_item(raw, proc, cluster_id))
    return NewsList(items=items)


@router.get("/news/{raw_id}", response_model=NewsItem)
async def get_news(raw_id: int, session: AsyncSession = Depends(db_session)) -> NewsItem:
    stmt = (
        select(RawContent, ProcessedContent, ClusterItem.cluster_id)
        .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .outerjoin(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
        .where(RawContent.id == raw_id)
    )
    res = await session.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    raw, proc, cluster_id = row
    return _to_news_item(raw, proc, cluster_id)


@router.post("/reprocess/{raw_id}", status_code=202)
async def reprocess(
    raw_id: int, background: BackgroundTasks, session: AsyncSession = Depends(db_session)
) -> dict[str, str]:
    raw = await session.get(RawContent, raw_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="not found")
    # Clear the existing processed row so the enrichment pass picks it up.
    existing = await session.execute(
        select(ProcessedContent).where(ProcessedContent.raw_content_id == raw_id)
    )
    proc = existing.scalar_one_or_none()
    if proc is not None:
        proc.cleaned_summary = None
        proc.is_noise = False
        await session.commit()
    # Find owning cluster and trigger enrichment.
    cluster_q = await session.execute(
        select(ClusterItem.cluster_id).where(ClusterItem.raw_content_id == raw_id)
    )
    cluster_id_row = cluster_q.first()
    if cluster_id_row is None:
        raise HTTPException(status_code=409, detail="not yet clustered")
    cluster_id = int(cluster_id_row[0])

    # Enrichment makes several LLM round-trips; run it off the request path with its
    # own session so a pooled request connection isn't pinned for seconds of latency.
    async def _run() -> None:
        async with SessionLocal() as bg_session:
            try:
                await EnrichmentService(bg_session)._enrich_cluster(cluster_id, raw_id)  # noqa: SLF001
            except Exception as e:  # noqa: BLE001
                log.error("reprocess.enrich_failed", raw_id=raw_id, cluster_id=cluster_id, err=str(e))

    background.add_task(_run)
    return {"status": "scheduled"}
