from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.ai.openai_client import json_completion
from app.ai.players import detect_players
from app.ai.prompts import CLASSIFY_NOISE_V1_SYSTEM, CLASSIFY_NOISE_V1_USER, INJECTION_GUARD
from app.ai.sanitize import neutralize, wrap
from app.logging_config import get_logger
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.repositories.processed_repo import ProcessedContentRepository
from app.repositories.raw_content_repo import RawContentRepository

log = get_logger(__name__)

_MAX_BODY = 6000


class ClassificationService:
    """Single-LLM-call noise filter. Skips items that already have processed rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.raw_repo = RawContentRepository(session)
        self.proc_repo = ProcessedContentRepository(session)

    async def classify_pending(self) -> tuple[int, int]:
        pending = await self.raw_repo.list_without_processed(limit=2000)
        valuable = 0
        noisy = 0
        for raw in pending:
            try:
                payload = await json_completion(
                    system=INJECTION_GUARD + CLASSIFY_NOISE_V1_SYSTEM,
                    user=CLASSIFY_NOISE_V1_USER.format(
                        title=neutralize(raw.title, 500),
                        url=neutralize(raw.url, 500),
                        body=wrap(raw.raw_text, _MAX_BODY),
                    ),
                    temperature=0.0,
                )
            except Exception as e:
                log.warning("classify.failed", raw_id=raw.id, err=str(e))
                continue

            category = (payload.get("category") or "medium").lower()
            theme = (payload.get("theme") or "").lower() or None
            importance_tier = (payload.get("importance_tier") or "").lower() or None
            if theme == "irrelevante":
                category = "noise"
            if importance_tier not in {"alta", "media", "baja"}:
                importance_tier = None
            is_noise = category == "noise"
            processed = ProcessedContent(
                raw_content_id=raw.id,
                cleaned_summary=None,
                key_topics=payload.get("tags", []) or [],
                is_noise=is_noise,
                rejected_reason=payload.get("reasoning") if is_noise else None,
                ai_generated_insights={"classification": payload},
                theme=theme,
                importance_tier=importance_tier,
            )
            await self.proc_repo.add(processed)
            await self.session.commit()
            if is_noise:
                noisy += 1
            else:
                valuable += 1
        log.info("classify.done", valuable=valuable, noisy=noisy)
        return valuable, noisy


async def backfill_players(session: AsyncSession) -> int:
    """Tag each processed item with the top players it mentions (OpenAI, Anthropic,
    Google, Meta, NVIDIA, ...). Deterministic keyword/alias match — free, no LLM.
    Idempotent: recomputes and updates only when the result changes."""
    rows = await session.execute(
        select(ProcessedContent, RawContent.title)
        .join(RawContent, RawContent.id == ProcessedContent.raw_content_id)
    )
    changed = 0
    for proc, title in rows.all():
        text_parts = [title or "", proc.cleaned_summary or ""]
        text_parts.extend(proc.key_topics or [])
        players = detect_players(" \n ".join(text_parts))
        if players != (proc.players or []):
            proc.players = players
            changed += 1
    if changed:
        await session.commit()
    log.info("players.backfill", updated=changed)
    return changed
