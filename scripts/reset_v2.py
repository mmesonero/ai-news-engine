"""Drop noisy sources + clear processed_content so the new (stricter) enrichment
prompt re-scores everything from scratch."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.models.source import Source

# Sources to drop — keep dataset signal-dense.
DROP_NAMES = {
    "Google DeepMind Blog",   # 89 retrospectives/PR posts flooded the rankings
}


async def main() -> None:
    async with SessionLocal() as session:
        # 1. Drop sources + cascade their raw_content.
        sources = (await session.execute(select(Source))).scalars().all()
        dropped = []
        for s in sources:
            if s.name in DROP_NAMES:
                # Cascade FK deletes raw_content + embeddings + cluster_items + processed_content.
                await session.execute(delete(RawContent).where(RawContent.source_id == s.id))
                await session.delete(s)
                dropped.append(s.name)
        await session.commit()
        print(f"dropped sources: {dropped}")

        # 2. Wipe processed_content so the new scoring prompt re-runs.
        res = await session.execute(delete(ProcessedContent))
        print(f"cleared {res.rowcount} processed_content rows (will be re-classified+enriched)")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
