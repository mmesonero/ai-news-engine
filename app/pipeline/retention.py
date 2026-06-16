"""Archive-friendly retention job.

Instead of DELETING old content, this blanks the HEAVY data (the embeddings
table row + `raw_text`) once an item is past the dedup/enrichment window, while
KEEPING the `raw_content` row + its `processed_content` (title_es, summary,
theme, score, players, image_url) + cluster forever.

Rationale: the heavy data (1536-dim embedding ≈ 6KB + full body text) is only
needed for semantic dedup (last `RETENTION_DAYS` days) and one-time enrichment.
The light metadata the web/Telegram render is ~1KB/story, so the site can be a
permanent archive (weeks/years) at negligible Neon cost. Mirrors
`prune_duplicate_members` — the row stays so cross-source counts keep working
and `embed_pending` never re-embeds it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.models.embedding import Embedding
from app.models.raw_content import RawContent

log = get_logger(__name__)


async def run_retention() -> dict[str, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    log.info("retention.start", cutoff=cutoff.isoformat(), days=settings.retention_days)

    async with SessionLocal() as session:
        # Rows older than the window that still carry heavy data.
        target = (
            await session.execute(
                select(RawContent.id)
                .where(RawContent.fetched_at < cutoff)
                .where(RawContent.embedding_pruned.is_(False))
            )
        ).scalars().all()

        if not target:
            log.info("retention.nothing_to_prune")
            return {"raw_pruned": 0}

        ids = [int(i) for i in target]
        # Drop the heavy embedding + blank the body, but KEEP the row + processed +
        # cluster. The story stays visible on the web/archive forever.
        await session.execute(delete(Embedding).where(Embedding.raw_content_id.in_(ids)))
        await session.execute(
            update(RawContent)
            .where(RawContent.id.in_(ids))
            .values(raw_text="", embedding_pruned=True)
        )
        await session.commit()

    metrics = {"raw_pruned": len(ids)}
    log.info("retention.done", **metrics)
    return metrics


def main() -> None:
    configure_logging()
    asyncio.run(run_retention())


if __name__ == "__main__":
    main()
