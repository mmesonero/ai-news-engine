from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_client import embed_batch
from app.config import settings
from app.logging_config import get_logger
from app.repositories.embedding_repo import EmbeddingRepository
from app.repositories.raw_content_repo import RawContentRepository

log = get_logger(__name__)

_MAX_CHARS = 8000  # ~ safe ceiling for embedding input


def _prep_text(title: str, body: str) -> str:
    """Concatenate title + body, truncated. Title matters more for short-form dedup."""
    joined = f"{title}\n\n{body}"
    return joined[:_MAX_CHARS]


class EmbeddingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.raw_repo = RawContentRepository(session)
        self.emb_repo = EmbeddingRepository(session)

    async def embed_pending(self, batch_size: int = 64) -> int:
        pending = await self.raw_repo.list_without_embeddings(limit=2000)
        if not pending:
            return 0
        log.info("embed.pending", count=len(pending))
        created = 0
        for i in range(0, len(pending), batch_size):
            chunk = pending[i : i + batch_size]
            texts = [_prep_text(r.title, r.raw_text) for r in chunk]
            vectors = await embed_batch(texts)
            for raw, vec in zip(chunk, vectors, strict=True):
                await self.emb_repo.add(
                    raw_content_id=raw.id,
                    vector=vec,
                    model=settings.openai_embedding_model,
                )
                created += 1
            await self.session.commit()
        log.info("embed.done", created=created)
        return created
