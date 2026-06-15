from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging_config import get_logger
from app.repositories.cluster_repo import ClusterRepository
from app.repositories.embedding_repo import EmbeddingRepository
from app.repositories.raw_content_repo import RawContentRepository

log = get_logger(__name__)


@dataclass
class DedupResult:
    new_clusters: int
    attached_to_existing: int
    duplicates: int


class DedupClusteringService:
    """Performs Layer-2 (semantic) dedup and greedy single-link clustering on new items.

    Layer 1 (exact dups) is already enforced upstream by UNIQUE constraints
    and content_hash checks in IngestionService.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.raw_repo = RawContentRepository(session)
        self.emb_repo = EmbeddingRepository(session)
        self.cluster_repo = ClusterRepository(session)

    async def process_new(self) -> DedupResult:
        result = DedupResult(0, 0, 0)
        # Iterate raw_content rows that have an embedding but no cluster membership.
        candidates = await self._list_unclustered_with_embeddings()
        log.info("dedup.candidates", count=len(candidates))

        for raw_id in candidates:
            # An earlier iteration may have side-effect-attached this raw_id
            # (it was the unclustered neighbour of an earlier candidate).
            # Skip — its cluster is already correct.
            if await self.cluster_repo.cluster_for(raw_id) is not None:
                continue
            emb = await self.emb_repo.get_for(raw_id)
            if emb is None:
                continue
            neighbours = await self.emb_repo.nearest_within(
                vector=list(emb.embedding),
                lookback_days=settings.dedup_lookback_days,
                limit=5,
                exclude_id=raw_id,
            )
            attached = False
            for nb_emb, sim in neighbours:
                if sim >= settings.dedup_threshold:
                    # Exact-story duplicate — attach to neighbour's cluster.
                    cluster = await self.cluster_repo.cluster_for(nb_emb.raw_content_id)
                    if cluster is None:
                        cluster = await self.cluster_repo.create(
                            representative_id=nb_emb.raw_content_id
                        )
                        await self.cluster_repo.attach(
                            cluster_id=cluster.id,
                            raw_content_id=nb_emb.raw_content_id,
                            similarity=1.0,
                        )
                    await self.cluster_repo.attach(
                        cluster_id=cluster.id,
                        raw_content_id=raw_id,
                        similarity=sim,
                    )
                    result.duplicates += 1
                    result.attached_to_existing += 1
                    attached = True
                    break
                if sim >= settings.cluster_threshold:
                    # Related — same cluster, different angle.
                    cluster = await self.cluster_repo.cluster_for(nb_emb.raw_content_id)
                    if cluster is None:
                        cluster = await self.cluster_repo.create(
                            representative_id=nb_emb.raw_content_id
                        )
                        await self.cluster_repo.attach(
                            cluster_id=cluster.id,
                            raw_content_id=nb_emb.raw_content_id,
                            similarity=1.0,
                        )
                    await self.cluster_repo.attach(
                        cluster_id=cluster.id,
                        raw_content_id=raw_id,
                        similarity=sim,
                    )
                    result.attached_to_existing += 1
                    attached = True
                    break
            if not attached:
                cluster = await self.cluster_repo.create(representative_id=raw_id)
                await self.cluster_repo.attach(
                    cluster_id=cluster.id, raw_content_id=raw_id, similarity=1.0
                )
                result.new_clusters += 1
            await self.session.commit()
        log.info(
            "dedup.done",
            new_clusters=result.new_clusters,
            attached=result.attached_to_existing,
            duplicates=result.duplicates,
        )
        return result

    async def _list_unclustered_with_embeddings(self) -> list[int]:
        from sqlalchemy import select

        from app.models.cluster import ClusterItem
        from app.models.embedding import Embedding

        stmt = (
            select(Embedding.raw_content_id)
            .outerjoin(ClusterItem, ClusterItem.raw_content_id == Embedding.raw_content_id)
            .where(ClusterItem.raw_content_id.is_(None))
            .order_by(Embedding.raw_content_id)
        )
        res = await self.session.execute(stmt)
        return [int(r[0]) for r in res.all()]
