from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cluster import ClusterItem, ContentCluster


class ClusterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, representative_id: int, topic: str | None = None) -> ContentCluster:
        cluster = ContentCluster(representative_content_id=representative_id, cluster_topic=topic)
        self.session.add(cluster)
        await self.session.flush()
        return cluster

    async def attach(
        self, cluster_id: int, raw_content_id: int, similarity: float
    ) -> ClusterItem:
        item = ClusterItem(
            cluster_id=cluster_id,
            raw_content_id=raw_content_id,
            similarity_score=similarity,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def cluster_for(self, raw_content_id: int) -> ContentCluster | None:
        res = await self.session.execute(
            select(ContentCluster)
            .join(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
            .where(ClusterItem.raw_content_id == raw_content_id)
        )
        return res.scalar_one_or_none()

    async def list_with_counts(self, limit: int = 50) -> list[tuple[ContentCluster, int]]:
        count_col = func.count(ClusterItem.raw_content_id).label("member_count")
        stmt = (
            select(ContentCluster, count_col)
            .outerjoin(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
            .group_by(ContentCluster.id)
            .order_by(count_col.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return [(row[0], int(row[1])) for row in res.all()]

    async def members(self, cluster_id: int) -> list[ClusterItem]:
        res = await self.session.execute(
            select(ClusterItem).where(ClusterItem.cluster_id == cluster_id)
        )
        return list(res.scalars())

    async def set_topic(self, cluster_id: int, topic: str) -> None:
        cluster = await self.session.get(ContentCluster, cluster_id)
        if cluster is not None:
            cluster.cluster_topic = topic
            await self.session.flush()
