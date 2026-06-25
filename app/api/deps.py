from __future__ import annotations

import hmac
from collections.abc import AsyncIterator

from fastapi import Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal


async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate /admin/* endpoints. If `settings.admin_token` is unset (local dev), allow
    through unchanged; if set, require a matching `X-Admin-Token` header (constant-time
    compare) and 401 otherwise. CORS does not protect non-browser callers, so this is
    the real guard if the API is ever exposed."""
    expected = settings.admin_token
    if not expected:
        return
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="invalid or missing admin token")
