"""Seed the initial source catalog. Idempotent — re-running is a no-op.

Curated for signal density:
  - OpenAI / Anthropic exposed via YouTube only (their blogs are PR-heavy).
  - Google DeepMind Blog intentionally excluded (89 retrospective/PR posts
    inflated rankings; their YT presence covers the news angle).
  - One source per outlet (TC AI vs TC general — keep AI vertical only).
  - YouTube AI creators for early signals.
"""
from __future__ import annotations

import asyncio

from app.database import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.models.source import Source
from app.repositories.source_repo import SourceRepository

log = get_logger(__name__)

DEFAULT_SOURCES: list[dict] = [
    # --- AI LABS (YouTube only) ---
    {"name": "OpenAI", "type": "youtube", "url": "@OpenAI",
     "group_name": "OpenAI", "config_json": {"max_results": 8, "require_ai_topic": False}},
    {"name": "Anthropic (Claude)", "type": "youtube", "url": "@claude",
     "group_name": "Anthropic", "config_json": {"max_results": 5, "require_ai_topic": False}},

    # --- AI VERTICALS (RSS) ---
    {"name": "TechCrunch AI", "type": "rss",
     "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
     "group_name": "TechCrunch",
     "config_json": {"fetch_full_text": True, "require_ai_topic": False}},
    {"name": "The Verge AI", "type": "rss",
     "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
     "group_name": "The Verge",
     "config_json": {"fetch_full_text": True, "require_ai_topic": False}},
    {"name": "HuggingFace Blog", "type": "rss", "url": "https://huggingface.co/blog/feed.xml",
     "group_name": "HuggingFace", "config_json": {"require_ai_topic": False}},

    # --- YOUTUBE AI CREATORS ---
    {"name": "AI Explained", "type": "youtube", "url": "UCNJ1Ymd5yFuUPtn21xtRbbw",
     "config_json": {"max_results": 5}},
    {"name": "Two Minute Papers", "type": "youtube", "url": "UCbfYPyITQ-7l4upoX8nvctg",
     "config_json": {"max_results": 5}},
    {"name": "Inteligencia Artificial (ES)", "type": "youtube",
     "url": "@la_inteligencia_artificial",
     "config_json": {"max_results": 5}},
]


async def seed() -> None:
    configure_logging()
    async with SessionLocal() as session:
        repo = SourceRepository(session)
        existing_urls = {s.url for s in await repo.list_all()}
        added = 0
        for spec in DEFAULT_SOURCES:
            if spec["url"] in existing_urls:
                continue
            await repo.add(
                Source(
                    name=spec["name"],
                    type=spec["type"],
                    url=spec["url"],
                    active=True,
                    config_json=spec.get("config_json", {}),
                    group_name=spec.get("group_name"),
                )
            )
            added += 1
        await session.commit()
        log.info("seed.done", added=added, total=len(DEFAULT_SOURCES))


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
