"""Daily briefing — last 24h non-noise news grouped by theme, ordered by importance.

Modeled on Executive Lab's WF-03 output: cluster representatives only, capped per theme,
themes returned in a fixed display order so frontends don't have to think about it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.schemas.news import NewsItem, ProcessedRead
from pydantic import BaseModel

router = APIRouter()

# Display order matches Executive Lab's 3-section briefing structure.
THEME_ORDER: list[str] = [
    "nuevo_modelo",
    "herramienta_nueva",
    "nueva_funcionalidad",
    "movimiento_empresarial",
    "caso_practico",
    "insight_negocio",
    "ejemplo_uso",
    "noticia_relevante",
]

THEME_LABEL: dict[str, str] = {
    "nuevo_modelo": "Nuevos modelos",
    "herramienta_nueva": "Herramientas nuevas",
    "nueva_funcionalidad": "Nuevas funcionalidades",
    "movimiento_empresarial": "Movimientos empresariales",
    "caso_practico": "Casos prácticos",
    "insight_negocio": "Insights de negocio",
    "ejemplo_uso": "Ejemplos de uso",
    "noticia_relevante": "Otras noticias relevantes",
}

TIER_RANK = {"alta": 3, "media": 2, "baja": 1}


class ThemeBlock(BaseModel):
    theme: str
    label: str
    items: list[NewsItem]


class DailyBriefing(BaseModel):
    since: datetime
    until: datetime
    total: int
    blocks: list[ThemeBlock]


@router.get("/briefing/daily", response_model=DailyBriefing)
async def briefing_daily(
    session: AsyncSession = Depends(db_session),
    hours: int = Query(default=24, ge=1, le=168),
    per_theme: int = Query(default=8, ge=1, le=30),
    min_tier: str = Query(default="baja", pattern="^(alta|media|baja)$"),
) -> DailyBriefing:
    """Last-N-hours non-noise representatives, grouped by theme, ordered alta→baja."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    min_rank = TIER_RANK[min_tier]
    tier_rank = case(
        (ProcessedContent.importance_tier == "alta", 3),
        (ProcessedContent.importance_tier == "media", 2),
        (ProcessedContent.importance_tier == "baja", 1),
        else_=0,
    ).label("tier_rank")

    # Per-cluster cross-source stats: how many articles, from how many distinct
    # outlets. A story independently covered by many outlets is a stronger
    # signal, so we reward it in the ordering (and surface the count).
    stats_subq = (
        select(
            ClusterItem.cluster_id.label("cid"),
            func.count(ClusterItem.raw_content_id).label("members"),
            func.count(func.distinct(RawContent.source_id)).label("sources"),
        )
        .join(RawContent, RawContent.id == ClusterItem.raw_content_id)
        .group_by(ClusterItem.cluster_id)
        .subquery()
    )

    members = func.coalesce(stats_subq.c.members, 1)
    sources = func.coalesce(stats_subq.c.sources, 1)
    # +8 per extra distinct outlet, capped at +20 (same rule as trending/weekly).
    source_boost = func.least(20, (sources - 1) * 8)
    boosted = (func.coalesce(ProcessedContent.importance_score, 0) + source_boost).label("boosted")

    rep_subq = select(ContentCluster.representative_content_id)
    stmt = (
        select(
            RawContent,
            ProcessedContent,
            ClusterItem.cluster_id,
            tier_rank,
            members.label("members"),
            sources.label("sources"),
            boosted,
        )
        .join(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .outerjoin(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
        .outerjoin(stats_subq, stats_subq.c.cid == ClusterItem.cluster_id)
        .where(ProcessedContent.is_noise.is_(False))
        .where(ProcessedContent.theme.isnot(None))
        .where(ProcessedContent.theme != "irrelevante")
        .where(
            or_(
                ClusterItem.cluster_id.is_(None),
                RawContent.id.in_(rep_subq),
            )
        )
        .where(
            or_(
                RawContent.published_at >= since,
                (RawContent.published_at.is_(None)) & (RawContent.fetched_at >= since),
            )
        )
        .where(tier_rank >= min_rank)
        .order_by(
            desc(tier_rank),
            desc(boosted),
            desc(RawContent.published_at),
        )
    )
    res = await session.execute(stmt)

    by_theme: dict[str, list[NewsItem]] = {t: [] for t in THEME_ORDER}
    total = 0
    for raw, proc, cluster_id, _rank, member_count, source_count, _boosted in res.all():
        theme = proc.theme or "noticia_relevante"
        if theme not in by_theme:
            by_theme[theme] = []
        if len(by_theme[theme]) >= per_theme:
            continue
        by_theme[theme].append(
            NewsItem(
                id=raw.id,
                source_id=raw.source_id,
                title=raw.title,
                url=raw.url,
                author=raw.author,
                published_at=raw.published_at,
                cluster_id=cluster_id,
                member_count=int(member_count) if member_count is not None else 1,
                distinct_sources=int(source_count) if source_count is not None else 1,
                processed=ProcessedRead.model_validate(proc),
            )
        )
        total += 1

    blocks = [
        ThemeBlock(theme=t, label=THEME_LABEL.get(t, t), items=by_theme[t])
        for t in THEME_ORDER
        if by_theme.get(t)
    ]
    return DailyBriefing(since=since, until=now, total=total, blocks=blocks)
