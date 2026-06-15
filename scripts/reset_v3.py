"""Drop sources re-introduced by stale seeds; clear processed_content; keep raw."""
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

DROP_NAMES = {
    "Google DeepMind Blog",
    "OpenAI Blog",
    "Anthropic News",
    "Anthropic",            # @anthropic-ai YT (keep only Claude)
    "TechCrunch",           # generalist — TC AI covers
    "The Verge",            # generalist
    "Popular Science",
    "Hackaday",
}


async def main() -> None:
    async with SessionLocal() as session:
        sources = (await session.execute(select(Source))).scalars().all()
        dropped = []
        for s in sources:
            if s.name in DROP_NAMES:
                await session.execute(delete(RawContent).where(RawContent.source_id == s.id))
                await session.delete(s)
                dropped.append(s.name)
        await session.commit()
        print(f"dropped sources: {dropped}")

        cleared = (await session.execute(delete(ProcessedContent))).rowcount
        await session.commit()
        print(f"cleared {cleared} processed_content rows")

        finals = (await session.execute(select(Source).order_by(Source.name))).scalars().all()
        print(f"\nFinal source catalog ({len(finals)}):")
        for s in finals:
            print(f"  {s.id:3d}  [{s.type:7s}]  group={s.group_name or '-':12s}  {s.name}")


if __name__ == "__main__":
    asyncio.run(main())
