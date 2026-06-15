from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[Source]:
        res = await self.session.execute(select(Source).where(Source.active.is_(True)))
        return list(res.scalars())

    async def list_all(self) -> list[Source]:
        res = await self.session.execute(select(Source).order_by(Source.id))
        return list(res.scalars())

    async def get_by_url(self, url: str) -> Source | None:
        res = await self.session.execute(select(Source).where(Source.url == url))
        return res.scalar_one_or_none()

    async def add(self, source: Source) -> Source:
        self.session.add(source)
        await self.session.flush()
        return source
