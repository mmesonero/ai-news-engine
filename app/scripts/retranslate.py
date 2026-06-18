"""One-off: re-translate all existing enriched content to English.

The enrichment prompt now outputs English. This nulls the stored display title +
summary for every NON-noise cluster representative, then re-runs enrichment over
them so the existing back-catalogue gets regenerated in English.

Run inside GitHub Actions (needs DATABASE_URL + SYNC_DATABASE_URL + OPENAI_API_KEY):
    python -m app.scripts.retranslate
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select, update

from app.database import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.models.cluster import ContentCluster
from app.models.processed_content import ProcessedContent
from app.services.enrichment_service import EnrichmentService

log = get_logger(__name__)


async def run() -> int:
    # 1. Null title_es + cleaned_summary on representatives so they re-enrich.
    async with SessionLocal() as session:
        rep_ids = select(ContentCluster.representative_content_id)
        res = await session.execute(
            update(ProcessedContent)
            .where(ProcessedContent.raw_content_id.in_(rep_ids))
            .where(ProcessedContent.is_noise.is_(False))
            .values(title_es=None, cleaned_summary=None)
        )
        await session.commit()
        log.info("retranslate.cleared", rows=res.rowcount)

    # 2. Re-enrich (English now).
    async with SessionLocal() as session:
        n = await EnrichmentService(session).enrich_pending()
        log.info("retranslate.done", reenriched=n)
    return n


def main() -> None:
    configure_logging()
    print("re-enriched:", asyncio.run(run()))


if __name__ == "__main__":
    main()
