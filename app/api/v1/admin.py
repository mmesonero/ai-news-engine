from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from app.api.deps import require_admin
from app.logging_config import get_logger
from app.pipeline.daily import run_daily_pipeline
from app.pipeline.retention import run_retention

# All admin routes require the admin token when one is configured (see require_admin).
router = APIRouter(dependencies=[Depends(require_admin)])
log = get_logger(__name__)

_lock = asyncio.Lock()
_retention_lock = asyncio.Lock()


class RunResponse(BaseModel):
    status: str
    detail: str


@router.post("/admin/run-pipeline", response_model=RunResponse, status_code=202)
async def run_pipeline_now(background: BackgroundTasks) -> RunResponse:
    """Trigger the daily pipeline immediately in the background.
    Guarded by an in-process lock so concurrent calls don't double-run."""
    if _lock.locked():
        return RunResponse(status="busy", detail="pipeline already running")

    async def _runner() -> None:
        async with _lock:
            try:
                await run_daily_pipeline()
            except Exception as e:
                log.error("admin.pipeline_failed", err=str(e))

    background.add_task(_runner)
    return RunResponse(status="accepted", detail="pipeline started")


@router.post("/admin/run-retention", response_model=RunResponse, status_code=202)
async def run_retention_now(background: BackgroundTasks) -> RunResponse:
    if _retention_lock.locked():
        return RunResponse(status="busy", detail="retention already running")

    async def _runner() -> None:
        async with _retention_lock:
            try:
                await run_retention()
            except Exception as e:
                log.error("admin.retention_failed", err=str(e))

    background.add_task(_runner)
    return RunResponse(status="accepted", detail="retention started")
