"""Daily retention job.

Deletes raw_content rows older than `RETENTION_DAYS` days. Cascade FKs
clean up embeddings, cluster_items, and processed_content automatically.

We then sweep `content_clusters` that ended up with zero members and
delete those too — otherwise the DB would carry growing empty cluster
metadata forever.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.models.cluster import ClusterItem, ContentCluster
from app.models.raw_content import RawContent

log = get_logger(__name__)


async def run_retention() -> dict[str, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    log.info("retention.start", cutoff=cutoff.isoformat(), days=settings.retention_days)

    async with SessionLocal() as session:
        # 1. Count what we're about to delete (for logging).
        to_delete = await session.execute(
            select(func.count(RawContent.id)).where(RawContent.fetched_at < cutoff)
        )
        n_raw = int(to_delete.scalar_one())

        if n_raw == 0:
            log.info("retention.nothing_to_delete")
            return {"raw_deleted": 0, "clusters_pruned": 0}

        # 2. Delete raw_content. CASCADE cleans embeddings, cluster_items,
        #    processed_content via FK ondelete=CASCADE.
        await session.execute(delete(RawContent).where(RawContent.fetched_at < cutoff))

        # 3. Find clusters with zero members and remove them.
        empty_clusters_q = (
            select(ContentCluster.id)
            .outerjoin(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
            .group_by(ContentCluster.id)
            .having(func.count(ClusterItem.raw_content_id) == 0)
        )
        empty_ids = [int(r[0]) for r in (await session.execute(empty_clusters_q)).all()]
        if empty_ids:
            await session.execute(delete(ContentCluster).where(ContentCluster.id.in_(empty_ids)))

        await session.commit()

    metrics = {"raw_deleted": n_raw, "clusters_pruned": len(empty_ids)}
    log.info("retention.done", **metrics)
    return metrics


def main() -> None:
    configure_logging()
    asyncio.run(run_retention())


if __name__ == "__main__":
    main()
