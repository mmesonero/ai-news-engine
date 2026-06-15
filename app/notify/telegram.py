"""Telegram delivery of the daily briefing.

Sends the same content as the /briefing/daily endpoint to a Telegram chat:
last-24h non-noise cluster representatives, grouped by theme, ordered by
importance tier + cross-source coverage. No-op when not configured.

Called at the end of the daily pipeline (so both the local scheduler and the
GitHub Actions cron deliver to your phone).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.briefing import THEME_LABEL, THEME_ORDER
from app.config import settings
from app.logging_config import get_logger
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent

log = get_logger(__name__)

_TG_API = "https://api.telegram.org/bot{token}/sendMessage"
_MSG_LIMIT = 3800  # Telegram hard limit is 4096; leave headroom.
_TIER_EMOJI = {"alta": "🔴", "media": "🟡", "baja": "⚪"}


def _esc(s: str | None) -> str:
    """Escape for Telegram HTML parse_mode."""
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _collect(session: AsyncSession, hours: int) -> dict[str, list[dict]]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    tier_rank = case(
        (ProcessedContent.importance_tier == "alta", 3),
        (ProcessedContent.importance_tier == "media", 2),
        (ProcessedContent.importance_tier == "baja", 1),
        else_=0,
    ).label("tier_rank")

    stats_subq = (
        select(
            ClusterItem.cluster_id.label("cid"),
            func.count(func.distinct(RawContent.source_id)).label("sources"),
        )
        .join(RawContent, RawContent.id == ClusterItem.raw_content_id)
        .group_by(ClusterItem.cluster_id)
        .subquery()
    )
    sources = func.coalesce(stats_subq.c.sources, 1)
    source_boost = func.least(20, (sources - 1) * 8)
    boosted = (func.coalesce(ProcessedContent.importance_score, 0) + source_boost).label("boosted")

    rep_subq = select(ContentCluster.representative_content_id)
    stmt = (
        select(RawContent, ProcessedContent, sources.label("sources"), tier_rank, boosted)
        .join(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .outerjoin(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
        .outerjoin(stats_subq, stats_subq.c.cid == ClusterItem.cluster_id)
        .where(ProcessedContent.is_noise.is_(False))
        .where(ProcessedContent.theme.isnot(None))
        .where(ProcessedContent.theme != "irrelevante")
        .where(or_(ClusterItem.cluster_id.is_(None), RawContent.id.in_(rep_subq)))
        .where(
            or_(
                RawContent.published_at >= since,
                (RawContent.published_at.is_(None)) & (RawContent.fetched_at >= since),
            )
        )
        .where(tier_rank >= 1)
        .order_by(desc(tier_rank), desc(boosted), desc(RawContent.published_at))
    )
    res = await session.execute(stmt)

    by_theme: dict[str, list[dict]] = {}
    total = 0
    for raw, proc, src_count, _rank, _boost in res.all():
        if total >= settings.telegram_max_items:
            break
        theme = proc.theme or "noticia_relevante"
        by_theme.setdefault(theme, []).append(
            {
                "title": raw.title,
                "url": raw.url,
                "tier": proc.importance_tier or "baja",
                "sources": int(src_count) if src_count else 1,
            }
        )
        total += 1
    return by_theme


def _render(by_theme: dict[str, list[dict]]) -> str:
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    lines = [f"<b>📰 Briefing IA — {today}</b>"]
    for theme in THEME_ORDER:
        items = by_theme.get(theme)
        if not items:
            continue
        lines.append(f"\n<b>{_esc(THEME_LABEL.get(theme, theme))}</b>")
        for it in items:
            emoji = _TIER_EMOJI.get(it["tier"], "⚪")
            src = f" · 📡 {it['sources']}" if it["sources"] > 1 else ""
            title = _esc((it["title"] or "(sin título)")[:140])
            if it["url"]:
                lines.append(f'{emoji} <a href="{_esc(it["url"])}">{title}</a>{src}')
            else:
                lines.append(f"{emoji} {title}{src}")
    return "\n".join(lines)


def _chunk(text: str, limit: int = _MSG_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


async def _send(text: str) -> bool:
    url = _TG_API.format(token=settings.telegram_bot_token)
    async with httpx.AsyncClient(timeout=20) as client:
        ok = True
        for part in _chunk(text):
            try:
                r = await client.post(
                    url,
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": part,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                if r.status_code != 200:
                    log.warning("telegram.send_failed", status=r.status_code, body=r.text[:200])
                    ok = False
            except Exception as e:
                log.warning("telegram.send_error", err=str(e)[:200])
                ok = False
        return ok


async def send_daily_briefing(session: AsyncSession, hours: int = 24) -> int:
    """Send the daily briefing to Telegram. Returns items sent (0 = skipped/none)."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.info("telegram.not_configured")
        return 0
    by_theme = await _collect(session, hours)
    total = sum(len(v) for v in by_theme.values())
    if total == 0:
        log.info("telegram.nothing_to_send")
        return 0
    ok = await _send(_render(by_theme))
    log.info("telegram.sent", items=total, ok=ok)
    return total if ok else 0
