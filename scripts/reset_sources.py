"""Consolidate the source catalog per user instructions:
  - OpenAI: drop Blog RSS; add OpenAI YouTube channel.
  - Anthropic: drop Anthropic News HTML; keep ONLY @claude YouTube (drop @anthropic-ai).
  - Drop generalist outlets that duplicate AI-vertical feeds:
      TechCrunch general, The Verge general, Popular Science, Hackaday.
  - All other YouTube AI creators stay.

Also WIPE all raw_content (cascade clears embeddings/clusters/processed).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models.raw_content import RawContent
from app.models.cluster import ContentCluster
from app.models.source import Source

DROP_NAMES = {
    "OpenAI Blog",
    "Anthropic News",
    "Anthropic",            # @anthropic-ai YT — drop, keep only Claude
    "TechCrunch",           # generalist — TC AI covers AI angle
    "The Verge",            # generalist — Verge AI covers AI angle
    "Popular Science",      # most items off-topic anyway
    "Hackaday",             # always off-topic (DIY hardware)
}

# New: OpenAI's official YouTube channel (handle resolved at first fetch).
NEW_SOURCES = [
    {
        "name": "OpenAI",
        "type": "youtube",
        "url": "@OpenAI",
        "group_name": "OpenAI",
        "config_json": {"max_results": 8, "require_ai_topic": False},
    },
]


async def main() -> None:
    async with SessionLocal() as session:
        # 1. Wipe raw_content + cascades (embeddings, cluster_items, processed_content).
        n_raw = (await session.execute(select(RawContent.id))).all()
        await session.execute(delete(RawContent))
        # Wipe orphaned clusters (cluster_items already gone via cascade).
        await session.execute(delete(ContentCluster))
        await session.commit()
        print(f"wiped {len(n_raw)} raw_content rows and all clusters")

        # 2. Drop sources we no longer want.
        sources = (await session.execute(select(Source))).scalars().all()
        dropped = []
        for s in sources:
            if s.name in DROP_NAMES:
                await session.delete(s)
                dropped.append(s.name)
        await session.commit()
        print(f"dropped sources: {dropped}")

        # 3. Add new sources (skip if URL already present).
        existing_urls = {s.url for s in (await session.execute(select(Source))).scalars().all()}
        added = []
        for spec in NEW_SOURCES:
            if spec["url"] in existing_urls:
                continue
            session.add(Source(
                name=spec["name"], type=spec["type"], url=spec["url"],
                active=True, group_name=spec.get("group_name"),
                config_json=spec.get("config_json", {}),
            ))
            added.append(spec["name"])
        await session.commit()
        print(f"added sources: {added}")

        # 4. Final source list summary.
        finals = (await session.execute(select(Source).order_by(Source.name))).scalars().all()
        print(f"\nFinal source catalog ({len(finals)}):")
        for s in finals:
            print(f"  {s.id:3d}  [{s.type:7s}]  group={s.group_name or '-':15s}  {s.name}")


if __name__ == "__main__":
    asyncio.run(main())
