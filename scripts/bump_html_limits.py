"""Bump max_articles for HTML-scraped sources so we capture more of the index page."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import SessionLocal
from app.models.source import Source


NEW_MAX = 30


async def main() -> None:
    async with SessionLocal() as session:
        srcs = (await session.execute(select(Source).where(Source.type == "html"))).scalars().all()
        for s in srcs:
            cfg = dict(s.config_json or {})
            cfg["max_articles"] = NEW_MAX
            s.config_json = cfg
            print(f"{s.name}: max_articles -> {NEW_MAX}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
