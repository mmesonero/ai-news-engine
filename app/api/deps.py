from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal


async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
