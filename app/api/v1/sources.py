from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.source import Source
from app.repositories.source_repo import SourceRepository
from app.schemas.source import SourceCreate, SourceRead

router = APIRouter()


@router.get("/sources", response_model=list[SourceRead])
async def list_sources(session: AsyncSession = Depends(db_session)) -> list[SourceRead]:
    repo = SourceRepository(session)
    rows = await repo.list_all()
    return [SourceRead.model_validate(r) for r in rows]


@router.post("/sources", response_model=SourceRead, status_code=201)
async def create_source(
    payload: SourceCreate, session: AsyncSession = Depends(db_session)
) -> SourceRead:
    repo = SourceRepository(session)
    if await repo.get_by_url(payload.url):
        raise HTTPException(status_code=409, detail="source with that URL already exists")
    source = Source(
        name=payload.name,
        type=payload.type,
        url=payload.url,
        active=payload.active,
        config_json=payload.config_json,
        group_name=payload.group_name,
    )
    await repo.add(source)
    await session.commit()
    return SourceRead.model_validate(source)
