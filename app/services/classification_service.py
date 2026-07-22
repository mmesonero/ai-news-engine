from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.ai.openai_client import json_completion
from app.ai.players import players_for
from app.ai.prompts import CLASSIFY_NOISE_V1_SYSTEM, CLASSIFY_NOISE_V1_USER, INJECTION_GUARD
from app.ai.sanitize import wrap_article
from app.logging_config import get_logger
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.repositories.processed_repo import ProcessedContentRepository
from app.repositories.raw_content_repo import RawContentRepository

log = get_logger(__name__)

_MAX_BODY = 6000

# Closed set of valid themes (ARCHITECTURE.md §8). Any off-list value the model
# returns is bucketed to "other" rather than being stored/rendered verbatim.
_VALID_THEMES = {
    "models", "tools", "features", "business", "cases", "insights", "tutorials", "other",
}


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
                        article=wrap_article(
                            title=raw.title, url=raw.url, body=raw.raw_text, max_body=_MAX_BODY
                        ),
                    ),
                    temperature=0.0,
                )
            except Exception as e:
                log.warning("classify.failed", raw_id=raw.id, err=str(e))
                continue

            if not payload:
                # Fail closed: an empty/invalid classifier payload (json_completion
                # returns {} on a decode failure or empty content) must NOT slip
                # through as a publishable default "medium" — treat it as noise.
                log.warning("classify.empty_payload", raw_id=raw.id)
                payload = {"category": "noise", "reasoning": "empty classifier payload"}

            category = (payload.get("category") or "medium").lower()
            theme = (payload.get("theme") or "").lower() or None
            importance_tier = (payload.get("importance_tier") or "").lower() or None
            if theme == "irrelevant":
                category = "noise"
            elif theme is not None and theme not in _VALID_THEMES:
                theme = "other"
            if importance_tier not in {"high", "medium", "low"}:
                importance_tier = None
            is_noise = category == "noise"
            # Coerce free-form model tags to a bounded list of clean strings: drop
            # non-strings, cap length + count. key_topics feed clustering + player
            # tagging, so unvalidated junk here corrupts both (and could break joins).
            key_topics = [
                str(t).strip()[:50]
                for t in (payload.get("tags") or [])
                if isinstance(t, (str, int, float)) and str(t).strip()
            ][:12]
            processed = ProcessedContent(
                raw_content_id=raw.id,
                cleaned_summary=None,
                key_topics=key_topics,
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
        # players_for enforces the fidelity rule: title + key_topics only, never
        # the summary (passing mentions caused false tags). See app/ai/players.py.
        try:
            players = players_for(title, proc.key_topics)
        except Exception as e:  # noqa: BLE001 — one bad row must not drop the stage
            log.warning("players.row_failed", raw_id=proc.raw_content_id, err=str(e)[:160])
            continue
        if players != (proc.players or []):
            proc.players = players
            changed += 1
    if changed:
        await session.commit()
    log.info("players.backfill", updated=changed)
    return changed
