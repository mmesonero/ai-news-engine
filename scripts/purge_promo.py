"""Purge already-stored promotional / CTA content from the DB.

Cascade FKs clean embeddings, cluster_items, processed_content. Empty
clusters are pruned at the end.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.ingestion.topic_filter import is_promo
from app.models.cluster import ClusterItem, ContentCluster
from app.models.raw_content import RawContent


async def main() -> None:
    async with SessionLocal() as session:
        candidates = (
            await session.execute(
                select(RawContent.id, RawContent.title, RawContent.raw_text)
            )
        ).all()
        to_delete = [
            cid for cid, title, body in candidates
            if is_promo(title or "", body or "")
        ]
        print(f"scanned {len(candidates)} items")
        print(f"promo items to delete: {len(to_delete)}")

        # Show sample for sanity-check.
        sample = (
            await session.execute(
                select(RawContent.title)
                .where(RawContent.id.in_(to_delete[:10]))
            )
        ).all()
        for (t,) in sample:
            print(f"  - {t[:120]}")

        if to_delete:
            await session.execute(delete(RawContent).where(RawContent.id.in_(to_delete)))
            await session.commit()
            print(f"deleted {len(to_delete)} raw_content rows")

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
