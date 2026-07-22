"""Seed the initial source catalog. Idempotent — re-running is a no-op.

Curated for signal density:
  - TEXT-ONLY. YouTube sources were dropped to cut token spend: video
    transcription (gpt-4o-transcribe), the per-video "worth transcribing"
    gatekeeper LLM call, and transcript-length bodies were the pipeline's
    biggest cost. Labs are now covered via their own RSS instead.
  - OpenAI / Google(DeepMind) via native RSS. Anthropic has no native feed,
    so it uses a keyless Google News query (best-effort, third-party coverage).
  - One source per outlet (TC AI vs TC general — keep AI vertical only).
"""
from __future__ import annotations

import asyncio

from app.database import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.models.source import Source
from app.repositories.source_repo import SourceRepository

log = get_logger(__name__)

DEFAULT_SOURCES: list[dict] = [
    # --- AI LABS (native RSS) ---
    {"name": "OpenAI", "type": "rss", "url": "https://openai.com/news/rss.xml",
     "group_name": "OpenAI",
     "config_json": {"fetch_full_text": True, "require_ai_topic": False}},
    {"name": "Google AI / DeepMind", "type": "rss",
     "url": "https://blog.google/technology/ai/rss/",
     "group_name": "Google",
     "config_json": {"fetch_full_text": True, "require_ai_topic": False}},
    # Anthropic publishes no native RSS — keyless Google News query as best-effort.
    # Third-party coverage (not the blog itself); dedup + classify handle the noise.
    {"name": "Anthropic (Claude)", "type": "rss",
     "url": "https://news.google.com/rss/search?q=anthropic%20claude%20when:7d&hl=en-US&gl=US&ceid=US:en",
     "group_name": "Anthropic",
     "config_json": {"require_ai_topic": True}},

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
