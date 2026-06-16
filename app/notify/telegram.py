"""Telegram delivery of the daily briefing.

Sends the same content as the /briefing/daily endpoint to a Telegram chat:
last-24h non-noise cluster representatives, grouped by theme, ordered by
importance tier + cross-source coverage. No-op when not configured.

Called at the end of the daily pipeline (so both the local scheduler and the
GitHub Actions cron deliver to your phone).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.links import detail_url
from app.logging_config import get_logger
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent

log = get_logger(__name__)

_TG_API = "https://api.telegram.org/bot{token}/sendMessage"

# Per-theme emoji shown at the start of each story message.
_THEME_EMOJI = {
    "nuevo_modelo": "🧠",
    "herramienta_nueva": "🛠️",
    "nueva_funcionalidad": "✨",
    "movimiento_empresarial": "💼",
    "caso_practico": "📈",
    "insight_negocio": "💡",
    "ejemplo_uso": "🧪",
    "noticia_relevante": "🌐",
}


def _esc(s: str | None) -> str:
    """Escape for Telegram HTML parse_mode."""
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _boosted(score: int | None, sources: int) -> int:
    """Importance score + cross-source coverage boost (+8/extra outlet, cap +20).
    More duplicates → higher score."""
    return (score or 0) + min(20, max(0, sources - 1) * 8)


async def _send_one(client: httpx.AsyncClient, text: str) -> int | None:
    """Send a message; return the Telegram message_id on success, else None."""
    url = _TG_API.format(token=settings.telegram_bot_token)
    try:
        r = await client.post(
            url,
            json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )
        data = r.json()
        if r.status_code != 200 or not data.get("ok"):
            log.warning("telegram.send_failed", status=r.status_code, body=r.text[:200])
            return None
        return int(data["result"]["message_id"])
    except Exception as e:
        log.warning("telegram.send_error", err=str(e)[:200])
        return None


async def _edit_one(client: httpx.AsyncClient, message_id: int, text: str) -> bool:
    url = _TG_API.format(token=settings.telegram_bot_token).replace("sendMessage", "editMessageText")
    try:
        r = await client.post(
            url,
            json={
                "chat_id": settings.telegram_chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )
        data = r.json()
        # "message is not modified" is a benign 400 — treat as success.
        if data.get("ok") or "not modified" in (data.get("description") or ""):
            return True
        log.warning("telegram.edit_failed", body=r.text[:200])
        return False
    except Exception as e:
        log.warning("telegram.edit_error", err=str(e)[:200])
        return False


def _render_story(
    theme: str,
    title: str,
    url: str,
    score: int | None,
    tier: str,
    sources: int,
    summary: str | None,
) -> str:
    """Format: <theme emoji> · <nota boosteada> · <título>  [📡N]
                <descripción breve>
                <enlace a la web>"""
    emoji = _THEME_EMOJI.get(theme, "🌐")
    boosted = _boosted(score, sources)
    nota = f"{boosted}/100" if score is not None else (tier or "—")
    t = _esc((title or "(sin título)")[:200])
    src = f"  📡{sources}" if sources > 1 else ""
    line1 = f"{emoji} · <b>{nota}</b> · <b>{t}</b>{src}"
    parts = [line1]
    if summary:
        parts.append(_esc(summary.strip()[:400]))
    # Link to OUR web detail page (summary + data + source inside), not the source.
    if url:
        parts.append(f'<a href="{_esc(detail_url(url))}">Ver en la web →</a>')
    return "\n\n".join(parts)


async def send_new_stories(session: AsyncSession, hours: int = 48, max_send: int = 30) -> int:
    """Send ONE Telegram message per NEW story (cluster not yet notified).
    Marks each as notified so it's never re-sent. Returns count sent."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.info("telegram.not_configured")
        return 0

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    sources = func.count(func.distinct(RawContent.source_id)).label("sources")
    tier_rank = case(
        (ProcessedContent.importance_tier == "alta", 3),
        (ProcessedContent.importance_tier == "media", 2),
        (ProcessedContent.importance_tier == "baja", 1),
        else_=0,
    ).label("tier_rank")

    stmt = (
        select(ContentCluster, RawContent, ProcessedContent, sources, tier_rank)
        .join(RawContent, RawContent.id == ContentCluster.representative_content_id)
        .join(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .join(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
        .where(ContentCluster.notified_at.is_(None))
        .where(ProcessedContent.is_noise.is_(False))
        .where(ProcessedContent.theme.isnot(None))
        .where(ProcessedContent.theme != "irrelevante")
        .where(
            or_(
                RawContent.published_at >= since,
                (RawContent.published_at.is_(None)) & (RawContent.fetched_at >= since),
            )
        )
        .group_by(ContentCluster.id, RawContent.id, ProcessedContent.id)
        .order_by(desc(tier_rank), desc(func.coalesce(ProcessedContent.importance_score, 0)))
        .limit(max_send)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        log.info("telegram.no_new_stories")
        return 0

    sent = 0
    async with httpx.AsyncClient(timeout=20) as client:
        for cluster, raw, proc, src_count, _rank in rows:
            text = _render_story(
                theme=proc.theme or "noticia_relevante",
                title=raw.title,
                url=raw.url,
                score=proc.importance_score,
                tier=proc.importance_tier or "baja",
                sources=int(src_count) if src_count else 1,
                summary=proc.cleaned_summary,
            )
            n_src = int(src_count) if src_count else 1
            msg_id = await _send_one(client, text)
            if msg_id is not None:
                cluster.notified_at = now
                cluster.telegram_message_id = msg_id
                cluster.telegram_sources = n_src
                await session.commit()  # mark per-message so a mid-run failure never re-sends
                sent += 1
                await asyncio.sleep(0.5)  # stay under Telegram per-chat rate limit
    log.info("telegram.new_stories_sent", sent=sent, candidates=len(rows))
    return sent


async def update_boosted_stories(session: AsyncSession, max_edits: int = 30) -> int:
    """Edit already-sent posts whose cross-source count grew since they were sent
    (a later duplicate arrived) → bump the counter + boosted score live. Returns
    number of posts edited."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return 0

    sources = func.count(func.distinct(RawContent.source_id)).label("sources")
    stmt = (
        select(ContentCluster, RawContent, ProcessedContent, sources)
        .join(RawContent, RawContent.id == ContentCluster.representative_content_id)
        .join(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .join(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
        .where(ContentCluster.telegram_message_id.isnot(None))
        .group_by(ContentCluster.id, RawContent.id, ProcessedContent.id)
        .having(func.count(func.distinct(RawContent.source_id)) > ContentCluster.telegram_sources)
        .limit(max_edits)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return 0

    edited = 0
    async with httpx.AsyncClient(timeout=20) as client:
        for cluster, raw, proc, src_count in rows:
            n_src = int(src_count) if src_count else 1
            text = _render_story(
                theme=proc.theme or "noticia_relevante",
                title=raw.title,
                url=raw.url,
                score=proc.importance_score,
                tier=proc.importance_tier or "baja",
                sources=n_src,
                summary=proc.cleaned_summary,
            )
            if await _edit_one(client, cluster.telegram_message_id, text):
                cluster.telegram_sources = n_src
                await session.commit()
                edited += 1
                await asyncio.sleep(0.5)
    log.info("telegram.boosted_edits", edited=edited, candidates=len(rows))
    return edited
