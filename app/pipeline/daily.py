from __future__ import annotations

import asyncio
import uuid

import structlog

from app.database import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.notify.linkedin_draft import build_and_send_breaking
from app.notify.telegram import send_new_stories, update_boosted_stories
from app.ingestion.image_extract import backfill_images
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


async def _run_stage(name: str, errors: list[str], fn) -> None:
    """Run one pipeline stage in its own DB session with error isolation.

    A stage failure is logged + recorded but does NOT abort the run, so the
    remaining stages — crucially the delivery ones (Telegram/LinkedIn) — still
    execute even if an upstream stage (embed/dedup/merge) throws. The run
    re-raises at the very end so the Actions job still goes red for visibility.
    `fn` receives the open session and writes its own metrics.
    """
    try:
        async with SessionLocal() as session:
            await fn(session)
    except Exception as e:  # noqa: BLE001
        log.error("pipeline.stage_failed", stage=name, err=str(e)[:300])
        errors.append(name)


async def run_daily_pipeline() -> dict[str, int]:
    """Idempotent end-to-end daily run. Each stage is safe to re-execute and is
    isolated: one failing stage never blocks the rest (notably delivery)."""
    run_id = uuid.uuid4().hex[:12]
    structlog.contextvars.bind_contextvars(run_id=run_id)
    log.info("pipeline.start")

    metrics: dict[str, int] = {}
    errors: list[str] = []

    async def _ingest(session):
        new_rows = await IngestionService(session).ingest_all_active()
        metrics["ingested"] = len(new_rows)
    await _run_stage("ingest", errors, _ingest)

    async def _embed(session):
        metrics["embedded"] = await EmbeddingService(session).embed_pending()
    await _run_stage("embed", errors, _embed)

    async def _dedup(session):
        r = await DedupClusteringService(session).process_new()
        metrics["new_clusters"] = r.new_clusters
        metrics["attached_to_existing"] = r.attached_to_existing
        metrics["semantic_duplicates"] = r.duplicates
    await _run_stage("dedup", errors, _dedup)

    # LLM-judged cluster merging — catches "same event, different angle" pairs
    # that fell below the cosine threshold (cosine-band + shared-entity candidates).
    async def _merge_borderline(session):
        r = await ClusterMergerService(session).merge_borderline()
        metrics["pairs_judged"] = r.pairs_evaluated
        metrics["pairs_merged"] = r.pairs_merged
        metrics["orphan_clusters_pruned"] = (
            metrics.get("orphan_clusters_pruned", 0) + await prune_orphan_clusters(session)
        )
    await _run_stage("merge_borderline", errors, _merge_borderline)

    # Holistic LLM grouping — the model sees every remaining cluster at once and
    # groups same-story clusters that pairwise signals missed.
    async def _merge_grouping(session):
        r = await ClusterMergerService(session).merge_by_llm_grouping()
        metrics["groups_judged"] = r.pairs_evaluated
        metrics["groups_merged"] = r.pairs_merged
        metrics["orphan_clusters_pruned"] = (
            metrics.get("orphan_clusters_pruned", 0) + await prune_orphan_clusters(session)
        )
        metrics["representatives_repaired"] = await repair_orphan_representatives(session)
    await _run_stage("merge_grouping", errors, _merge_grouping)

    async def _classify(session):
        valuable, noisy = await ClassificationService(session).classify_pending()
        metrics["classified_valuable"] = valuable
        metrics["classified_noise"] = noisy
    await _run_stage("classify", errors, _classify)

    async def _enrich(session):
        metrics["enriched_clusters"] = await EnrichmentService(session).enrich_pending()
    await _run_stage("enrich", errors, _enrich)

    # Tag items with the top players involved (free keyword match; current + future).
    async def _players(session):
        metrics["players_tagged"] = await backfill_players(session)
    await _run_stage("players", errors, _players)

    # Fetch a hero image (og:image / YouTube thumb) for stories that lack one.
    async def _images(session):
        metrics["images_found"] = await backfill_images(session)
    await _run_stage("images", errors, _images)

    # Storage saver: drop heavy embedding + raw_text of duplicate members
    # (rows kept so cross-source counts still work).
    async def _prune(session):
        metrics["members_pruned"] = await prune_duplicate_members(session)
    await _run_stage("prune_members", errors, _prune)

    # Deliver one Telegram message per NEW story; then edit posts whose source
    # count grew (a later duplicate → higher counter + boosted score).
    async def _telegram_send(session):
        metrics["telegram_sent"] = await send_new_stories(session)
    await _run_stage("telegram_send", errors, _telegram_send)

    async def _telegram_edit(session):
        metrics["telegram_edited"] = await update_boosted_stories(session)
    await _run_stage("telegram_edit", errors, _telegram_edit)

    # If a genuinely big story landed, send a ready-to-paste LinkedIn DRAFT to
    # Telegram for manual approval (once per story; no-op if nothing crosses the bar).
    async def _linkedin(session):
        metrics["linkedin_breaking"] = await build_and_send_breaking(session)
    await _run_stage("linkedin_breaking", errors, _linkedin)

    log.info("pipeline.done", failed_stages=len(errors), **metrics)
    structlog.contextvars.clear_contextvars()
    if errors:
        # Delivery has already been attempted; now fail loud so CI turns red.
        raise RuntimeError("pipeline stages failed: " + ", ".join(errors))
    return metrics


def main() -> None:
    configure_logging()
    asyncio.run(run_daily_pipeline())


if __name__ == "__main__":
    main()
