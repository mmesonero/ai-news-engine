from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.repositories.cluster_repo import ClusterRepository
from app.schemas.cluster import ClusterDetail, ClusterRead
from app.schemas.news import NewsItem, ProcessedRead

router = APIRouter()


def _news_item(raw: RawContent, processed: ProcessedContent | None, cluster_id: int | None) -> NewsItem:
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


@router.get("/clusters", response_model=list[ClusterRead])
async def list_clusters(
    session: AsyncSession = Depends(db_session),
    limit: int = 50,
) -> list[ClusterRead]:
    repo = ClusterRepository(session)
    pairs = await repo.list_with_counts(limit=limit)
    return [
        ClusterRead(
            id=c.id,
            cluster_topic=c.cluster_topic,
            representative_content_id=c.representative_content_id,
            member_count=count,
            created_at=c.created_at,
        )
        for c, count in pairs
    ]


@router.get("/clusters/{cluster_id}", response_model=ClusterDetail)
async def get_cluster(
    cluster_id: int, session: AsyncSession = Depends(db_session)
) -> ClusterDetail:
    cluster = await session.get(ContentCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="not found")

    members_stmt = (
        select(RawContent, ProcessedContent)
        .join(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
        .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .where(ClusterItem.cluster_id == cluster_id)
    )
    res = await session.execute(members_stmt)
    members: list[NewsItem] = []
    rep_item: NewsItem | None = None
    for raw, processed in res.all():
        item = _news_item(raw, processed, cluster_id)
        if raw.id == cluster.representative_content_id:
            rep_item = item
        members.append(item)

    return ClusterDetail(
        id=cluster.id,
        cluster_topic=cluster.cluster_topic,
        representative_content_id=cluster.representative_content_id,
        member_count=len(members),
        created_at=cluster.created_at,
        representative=rep_item,
        members=members,
    )
