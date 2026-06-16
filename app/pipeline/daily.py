from __future__ import annotations

import asyncio
import uuid

import structlog

from app.database import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.notify.telegram import send_new_stories
from app.services.classification_service import ClassificationService, backfill_players
from app.services.cluster_merger import (
    ClusterMergerService,
    prune_duplicate_members,
    prune_orphan_clusters,
    repair_orphan_representatives,
)
from app.services.dedup_clustering_service import DedupClusteringService
from app.services.embedding_service import EmbeddingService
from app.services.enrichment_service import EnrichmentService
from app.services.ingestion_service import IngestionService

log = get_logger(__name__)


async def run_daily_pipeline() -> dict[str, int]:
    """Idempotent end-to-end daily run. Each stage is safe to re-execute."""
    run_id = uuid.uuid4().hex[:12]
    structlog.contextvars.bind_contextvars(run_id=run_id)
    log.info("pipeline.start")

    metrics: dict[str, int] = {}

    async with SessionLocal() as session:
        ingestion = IngestionService(session)
        new_rows = await ingestion.ingest_all_active()
        metrics["ingested"] = len(new_rows)

    async with SessionLocal() as session:
        embedded = await EmbeddingService(session).embed_pending()
        metrics["embedded"] = embedded

    async with SessionLocal() as session:
        dedup_result = await DedupClusteringService(session).process_new()
        metrics["new_clusters"] = dedup_result.new_clusters
        metrics["attached_to_existing"] = dedup_result.attached_to_existing
        metrics["semantic_duplicates"] = dedup_result.duplicates

    # LLM-judged cluster merging — catches "same event, different angle" pairs
    # that fell below the cosine threshold (cosine-band + shared-entity candidates).
    async with SessionLocal() as session:
        merge_result = await ClusterMergerService(session).merge_borderline()
        metrics["pairs_judged"] = merge_result.pairs_evaluated
        metrics["pairs_merged"] = merge_result.pairs_merged
        pruned = await prune_orphan_clusters(session)
        metrics["orphan_clusters_pruned"] = pruned

    # Holistic LLM grouping — the model sees every remaining cluster at once and
    # groups same-story clusters that pairwise signals missed.
    async with SessionLocal() as session:
        group_result = await ClusterMergerService(session).merge_by_llm_grouping()
        metrics["groups_judged"] = group_result.pairs_evaluated
        metrics["groups_merged"] = group_result.pairs_merged
        metrics["orphan_clusters_pruned"] += await prune_orphan_clusters(session)
        metrics["representatives_repaired"] = await repair_orphan_representatives(session)

    async with SessionLocal() as session:
        valuable, noisy = await ClassificationService(session).classify_pending()
        metrics["classified_valuable"] = valuable
        metrics["classified_noise"] = noisy

    async with SessionLocal() as session:
        enriched = await EnrichmentService(session).enrich_pending()
        metrics["enriched_clusters"] = enriched

    # Tag items with the top players involved (free keyword match; current + future).
    async with SessionLocal() as session:
        metrics["players_tagged"] = await backfill_players(session)

    # Storage saver: drop heavy embedding + raw_text of duplicate members
    # (rows kept so cross-source counts still work).
    async with SessionLocal() as session:
        metrics["members_pruned"] = await prune_duplicate_members(session)

    # Deliver one Telegram message per NEW story (no-op if not configured).
    async with SessionLocal() as session:
        metrics["telegram_sent"] = await send_new_stories(session)

    log.info("pipeline.done", **metrics)
    structlog.contextvars.clear_contextvars()
    return metrics


def main() -> None:
    configure_logging()
    asyncio.run(run_daily_pipeline())


if __name__ == "__main__":
    main()
