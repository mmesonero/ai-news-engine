"""Switch Anthropic News from broken RSS to HTML scraping."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import SessionLocal
from app.models.source import Source


async def main() -> None:
    async with SessionLocal() as session:
        res = await session.execute(select(Source).where(Source.name == "Anthropic News"))
        src = res.scalar_one_or_none()
        if src is None:
            print("Anthropic News source not found")
            return
        src.type = "html"
        src.url = "https://www.anthropic.com/news"
        src.config_json = {
            "link_selector": 'a[href^="/news/"]',
            "title_selector": "h1",
            "body_selector": "article",
            "max_articles": 8,
        }
        await session.commit()
        print(f"updated id={src.id}: {src.type} {src.url}")
        print(f"config: {src.config_json}")


if __name__ == "__main__":
    asyncio.run(main())
