from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_content import RawContent


class RawContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        source_id: int,
        external_id: str | None,
        title: str,
        url: str,
        author: str | None,
        raw_text: str,
        published_at: datetime | None,
        content_hash: str,
        language: str | None,
        metadata: dict,
    ) -> RawContent | None:
        """Insert if new across all uniqueness keys; return the row, or None if already known.

        Both UNIQUE(url) and UNIQUE(source_id, external_id) can clash; SQLAlchemy's
        on_conflict_do_nothing can only target one. So we pre-check both, then insert,
        and as a final safety net swallow IntegrityError into None.
        """
        if await self._exists_url(url):
            return None
        if external_id is not None and await self._exists_external(source_id, external_id):
            return None

        row = RawContent(
            source_id=source_id,
            external_id=external_id,
            title=title,
            url=url,
            author=author,
            raw_text=raw_text,
            published_at=published_at,
            content_hash=content_hash,
            language=language,
            metadata_json=metadata,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return None
        return row

    async def _exists_url(self, url: str) -> bool:
        res = await self.session.execute(select(RawContent.id).where(RawContent.url == url).limit(1))
        return res.first() is not None

    async def _exists_external(self, source_id: int, external_id: str) -> bool:
        res = await self.session.execute(
            select(RawContent.id)
            .where(RawContent.source_id == source_id, RawContent.external_id == external_id)
            .limit(1)
        )
        return res.first() is not None

    async def by_id(self, raw_id: int) -> RawContent | None:
        res = await self.session.execute(select(RawContent).where(RawContent.id == raw_id))
        return res.scalar_one_or_none()

    async def exists_hash(self, content_hash: str) -> bool:
        res = await self.session.execute(
            select(RawContent.id).where(RawContent.content_hash == content_hash).limit(1)
        )
        return res.first() is not None

    async def list_recent(self, days: int, limit: int = 500) -> list[RawContent]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        res = await self.session.execute(
            select(RawContent)
            .where(or_(RawContent.published_at >= since, RawContent.fetched_at >= since))
            .order_by(desc(RawContent.published_at))
            .limit(limit)
        )
        return list(res.scalars())

    async def list_without_embeddings(self, limit: int = 2000) -> list[RawContent]:
        from app.models.embedding import Embedding

        res = await self.session.execute(
            select(RawContent)
            .outerjoin(Embedding, Embedding.raw_content_id == RawContent.id)
            .where(Embedding.id.is_(None))
            .where(RawContent.embedding_pruned.is_(False))  # don't re-embed pruned dupes
            .order_by(RawContent.id)
            .limit(limit)
        )
        return list(res.scalars())

    async def list_without_processed(self, limit: int = 2000) -> list[RawContent]:
        from app.models.processed_content import ProcessedContent

        res = await self.session.execute(
            select(RawContent)
            .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
            .where(ProcessedContent.id.is_(None))
            .order_by(RawContent.id)
            .limit(limit)
        )
        return list(res.scalars())

    async def count(self) -> int:
        from sqlalchemy import func

        res = await self.session.execute(select(func.count(RawContent.id)))
        return int(res.scalar_one())
