from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.logging_config import get_logger
from app.pipeline.daily import run_daily_pipeline
from app.pipeline.retention import run_retention

log = get_logger(__name__)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        run_daily_pipeline,
        trigger=CronTrigger.from_crontab(settings.pipeline_cron),
        id="daily-pipeline",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_retention,
        trigger=CronTrigger.from_crontab(settings.retention_cron),
        id="daily-retention",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    log.info(
        "scheduler.started",
        pipeline_cron=settings.pipeline_cron,
        retention_cron=settings.retention_cron,
        retention_days=settings.retention_days,
    )
    return scheduler


def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    scheduler.shutdown(wait=False)
    log.info("scheduler.stopped")
