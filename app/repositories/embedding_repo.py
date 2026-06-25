from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import Embedding
from app.models.raw_content import RawContent


class EmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, raw_content_id: int, vector: list[float], model: str) -> Embedding:
        emb = Embedding(raw_content_id=raw_content_id, embedding=vector, model=model)
        self.session.add(emb)
        await self.session.flush()
        return emb

    async def get_for(self, raw_content_id: int) -> Embedding | None:
        res = await self.session.execute(
            select(Embedding).where(Embedding.raw_content_id == raw_content_id)
        )
        return res.scalar_one_or_none()

    async def nearest_within(
        self,
        vector: list[float],
        *,
        lookback_days: int,
        limit: int = 5,
        exclude_id: int | None = None,
    ) -> list[tuple[Embedding, float]]:
        """Return (embedding, cosine_similarity) pairs for the nearest neighbours
        among raw_content rows newer than `lookback_days`."""
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        distance = Embedding.embedding.cosine_distance(vector)
        stmt = (
            select(Embedding, distance.label("dist"))
            .join(RawContent, RawContent.id == Embedding.raw_content_id)
            .where(RawContent.fetched_at >= since)
        )
        if exclude_id is not None:
            stmt = stmt.where(Embedding.raw_content_id != exclude_id)
        stmt = stmt.order_by(distance).limit(limit)
        # ivfflat defaults to probes=1 (scans only ~1/lists of the vectors), so real
        # near-duplicates can fall outside the probed lists and be missed. Widen the
        # search for this query (SET LOCAL → resets at transaction end). No-op if the
        # planner uses an exact scan or the index isn't ivfflat.
        await self.session.execute(text("SET LOCAL ivfflat.probes = 10"))
        res = await self.session.execute(stmt)
        return [(row[0], 1.0 - float(row[1])) for row in res.all()]
