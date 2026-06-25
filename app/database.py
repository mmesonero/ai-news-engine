from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        connect_args: dict = {}
        if "asyncpg" in settings.database_url:
            # Disable asyncpg's prepared-statement cache so the app also works on Neon's
            # pooled (PgBouncer transaction-mode) endpoint, which otherwise errors with
            # 'prepared statement "__asyncpg_stmt__" does not exist'. Negligible cost at
            # this QPS and harmless on the direct endpoint.
            connect_args["statement_cache_size"] = 0
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=300,  # recycle before Neon's idle timeout silently drops the socket
            future=True,
            connect_args=connect_args,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _session_factory


class _SessionLocalProxy:
    """Call `SessionLocal()` lazily — engine is only created the first time
    someone actually opens a session. Lets scripts/tests import the models
    package without needing the DB driver installed."""

    def __call__(self) -> AsyncSession:
        return get_session_factory()()


SessionLocal = _SessionLocalProxy()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
