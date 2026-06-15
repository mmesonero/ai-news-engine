"""Drop sources removed from the curated catalog."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models.raw_content import RawContent
from app.models.source import Source

DROP_NAMES = {
    "VentureBeat AI",
    "Wes Roth",
    "Matt Wolfe",
    "Yannic Kilcher",
}


async def main() -> None:
    async with SessionLocal() as session:
        srcs = (await session.execute(select(Source))).scalars().all()
        dropped = []
        for s in srcs:
            if s.name in DROP_NAMES:
                await session.execute(delete(RawContent).where(RawContent.source_id == s.id))
                await session.delete(s)
                dropped.append(s.name)
        await session.commit()
        print(f"dropped: {dropped}")
        finals = (await session.execute(select(Source).order_by(Source.name))).scalars().all()
        print(f"\nFinal sources ({len(finals)}):")
        for s in finals:
            print(f"  [{s.type:7s}]  {s.name}")


if __name__ == "__main__":
    asyncio.run(main())
