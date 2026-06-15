from __future__ import annotations

import hashlib
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion import get_ingestor
from app.ingestion.topic_filter import is_promo, matches_topic
from app.logging_config import get_logger
from app.models.raw_content import RawContent
from app.models.source import Source
from app.repositories.raw_content_repo import RawContentRepository
from app.repositories.source_repo import SourceRepository
from app.schemas.news import RawContentDraft

log = get_logger(__name__)

_WS = re.compile(r"\s+")


def _normalize_for_hash(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def _hash(title: str, body: str) -> str:
    h = hashlib.sha256()
    h.update(_normalize_for_hash(title).encode("utf-8"))
    h.update(b"\n")
    h.update(_normalize_for_hash(body).encode("utf-8"))
    return h.hexdigest()


class IngestionService:
    """Pulls drafts from ingestors and persists new ones into raw_content."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.raw_repo = RawContentRepository(session)
        self.source_repo = SourceRepository(session)

    async def ingest_all_active(self) -> list[RawContent]:
        sources = await self.source_repo.list_active()
        log.info("ingest.start", sources=len(sources))
        new_rows: list[RawContent] = []
        for source in sources:
            try:
                inserted = await self._ingest_source(source)
                new_rows.extend(inserted)
                log.info("ingest.source_ok", source=source.name, new=len(inserted))
            except Exception as e:
                log.error("ingest.source_failed", source=source.name, err=str(e))
        return new_rows

    async def _ingest_source(self, source: Source) -> list[RawContent]:
        ingestor = get_ingestor(source.type)
        drafts = await ingestor.fetch(source)
        inserted: list[RawContent] = []
        for d in drafts:
            row = await self._persist(source, d)
            if row is not None:
                inserted.append(row)
        await self.session.commit()
        return inserted

    async def _persist(self, source: Source, draft: RawContentDraft) -> RawContent | None:
        if not draft.title or not draft.url or not draft.raw_text:
            return None
        # Promo / CTA filter — applies to ALL sources (lab blogs don't post
        # "link in bio" anyway, so no risk of false positives).
        if is_promo(draft.title, draft.raw_text):
            log.info("ingest.promo_skip", source=source.name, title=draft.title[:80])
            return None
        # Per-source topical pre-filter. Default ON for all sources. Set
        # `config_json.require_ai_topic = false` to disable (e.g. for AI-lab blogs
        # whose every post is on-topic by definition).
        require_ai = (source.config_json or {}).get("require_ai_topic", True)
        if require_ai and not matches_topic(draft.title, draft.raw_text):
            log.info("ingest.off_topic_skip", source=source.name, title=draft.title[:80])
            return None
        content_hash = _hash(draft.title, draft.raw_text)
        if await self.raw_repo.exists_hash(content_hash):
            return None
        return await self.raw_repo.upsert(
            source_id=source.id,
            external_id=draft.external_id,
            title=draft.title,
            url=draft.url,
            author=draft.author,
            raw_text=draft.raw_text,
            published_at=draft.published_at,
            content_hash=content_hash,
            language=draft.language,
            metadata=draft.metadata,
        )
