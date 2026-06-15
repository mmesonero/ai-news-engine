"""Sync source.config_json.require_ai_topic from seed defaults, then retroactively
purge already-stored content that does NOT match the AI/business keyword filter.

Safe to re-run. Items removed cascade-delete their embeddings, processed_content,
and cluster_items. Empty clusters are pruned at the end.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.ingestion.topic_filter import matches_topic
from app.models.cluster import ClusterItem, ContentCluster
from app.models.raw_content import RawContent
from app.models.source import Source

# Sources whose every item is on-topic by definition.
EXEMPT_NAMES = {
    "OpenAI Blog", "Anthropic News",
    "Google DeepMind Blog", "HuggingFace Blog",
    "TechCrunch AI", "VentureBeat AI", "The Verge AI",
    # YouTube AI channels — generally on-topic; keep transcripts.
    "Anthropic", "Anthropic (Claude)",
    "Two Minute Papers", "AI Explained", "Yannic Kilcher",
    "Matt Wolfe", "Wes Roth",
    "Inteligencia Artificial (ES)",
}


async def main() -> None:
    async with SessionLocal() as session:
        # 1. Set require_ai_topic flag on sources.
        all_sources = (await session.execute(select(Source))).scalars().all()
        for s in all_sources:
            cfg = dict(s.config_json or {})
            cfg["require_ai_topic"] = s.name not in EXEMPT_NAMES
            s.config_json = cfg
        await session.commit()
        print(f"updated require_ai_topic on {len(all_sources)} sources")

        # 2. Identify off-topic items already in DB for sources where the flag is on.
        require_ids = [s.id for s in all_sources if s.name not in EXEMPT_NAMES]
        if not require_ids:
            return
        candidates = (
            await session.execute(
                select(RawContent.id, RawContent.title, RawContent.raw_text, RawContent.source_id)
                .where(RawContent.source_id.in_(require_ids))
            )
        ).all()
        to_delete = [
            cid for cid, title, body, _src in candidates
            if not matches_topic(title or "", body or "")
        ]
        print(f"scanned {len(candidates)} items in filtered sources")
        print(f"off-topic items to delete: {len(to_delete)}")

        if to_delete:
            # Cascade FKs clean embeddings, cluster_items, processed_content.
            await session.execute(delete(RawContent).where(RawContent.id.in_(to_delete)))
            await session.commit()
            print(f"deleted {len(to_delete)} raw_content rows")

        # 3. Prune now-empty clusters.
        empty_q = (
            select(ContentCluster.id)
            .outerjoin(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
            .group_by(ContentCluster.id)
            .having(func.count(ClusterItem.raw_content_id) == 0)
        )
        empty_ids = [int(r[0]) for r in (await session.execute(empty_q)).all()]
        if empty_ids:
            await session.execute(delete(ContentCluster).where(ContentCluster.id.in_(empty_ids)))
            await session.commit()
            print(f"pruned {len(empty_ids)} empty clusters")


if __name__ == "__main__":
    asyncio.run(main())
