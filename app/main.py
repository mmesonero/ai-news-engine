from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    admin,
    briefing,
    clusters,
    linkedin,
    news,
    sources,
    stats,
    trending,
    weekly_top,
)
from app.logging_config import configure_logging, get_logger
from app.middleware import RequestIdMiddleware
from app.scheduler.jobs import start_scheduler, stop_scheduler

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("app.starting")
    scheduler = start_scheduler()
    try:
        yield
    finally:
        stop_scheduler(scheduler)
        log.info("app.stopped")


app = FastAPI(
    title="AI News Intelligence Engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    # The viewer is served same-origin from this API; only allow localhost.
    # Wildcard + credentials is invalid and lets any visited site call the API.
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(news.router, prefix="/api/v1", tags=["news"])
app.include_router(clusters.router, prefix="/api/v1", tags=["clusters"])
app.include_router(trending.router, prefix="/api/v1", tags=["trending"])
app.include_router(linkedin.router, prefix="/api/v1", tags=["linkedin"])
app.include_router(sources.router, prefix="/api/v1", tags=["sources"])
app.include_router(stats.router, prefix="/api/v1", tags=["stats"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(weekly_top.router, prefix="/api/v1", tags=["weekly"])
app.include_router(briefing.router, prefix="/api/v1", tags=["briefing"])


_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/viewer", include_in_schema=False)
async def viewer() -> FileResponse:
    return FileResponse(
        Path(__file__).parent.parent / "viewer.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
