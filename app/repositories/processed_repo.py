from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.processed_content import ProcessedContent


class ProcessedContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, processed: ProcessedContent) -> ProcessedContent:
        self.session.add(processed)
        await self.session.flush()
        return processed

    async def upsert_for(self, raw_content_id: int, **fields: object) -> ProcessedContent:
        existing = await self.get_for(raw_content_id)
        if existing is None:
            new = ProcessedContent(raw_content_id=raw_content_id, **fields)  # type: ignore[arg-type]
            self.session.add(new)
            await self.session.flush()
            return new
        for k, v in fields.items():
            setattr(existing, k, v)
        await self.session.flush()
        return existing

    async def get_for(self, raw_content_id: int) -> ProcessedContent | None:
        res = await self.session.execute(
            select(ProcessedContent).where(ProcessedContent.raw_content_id == raw_content_id)
        )
        return res.scalar_one_or_none()

    async def top_linkedin(self, limit: int = 25) -> list[ProcessedContent]:
        res = await self.session.execute(
            select(ProcessedContent)
            .where(ProcessedContent.is_noise.is_(False))
            .order_by(desc(ProcessedContent.linkedin_potential_score))
            .limit(limit)
        )
        return list(res.scalars())
