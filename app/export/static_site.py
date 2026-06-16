"""Generate a self-contained static HTML page of the latest news.

No backend / no API: the data is rendered straight into the HTML, so the page
can be hosted on GitHub Pages (or any static host). Run after the pipeline:

    python -m app.export.static_site            # -> ./site/index.html
    python -m app.export.static_site /path.html # custom output

Grouped by theme, ordered by importance + cross-source coverage, last 7 days.
"""
from __future__ import annotations

import asyncio
import html
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, desc, func, or_, select

from app.api.v1.briefing import THEME_LABEL, THEME_ORDER
from app.database import SessionLocal
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent

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
    return html.escape(s or "")


async def _collect(hours: int, per_theme: int) -> tuple[dict[str, list[dict]], int]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    tier_rank = case(
        (ProcessedContent.importance_tier == "alta", 3),
        (ProcessedContent.importance_tier == "media", 2),
        (ProcessedContent.importance_tier == "baja", 1),
        else_=0,
    ).label("tier_rank")
    sources = func.count(func.distinct(RawContent.source_id))
    stats_subq = (
        select(
            ClusterItem.cluster_id.label("cid"),
            func.count(func.distinct(RawContent.source_id)).label("sources"),
        )
        .join(RawContent, RawContent.id == ClusterItem.raw_content_id)
        .group_by(ClusterItem.cluster_id)
        .subquery()
    )
    src = func.coalesce(stats_subq.c.sources, 1)
    boosted = (func.coalesce(ProcessedContent.importance_score, 0) + func.least(20, (src - 1) * 8)).label("boosted")
    rep_subq = select(ContentCluster.representative_content_id)

    stmt = (
        select(RawContent, ProcessedContent, src.label("sources"), tier_rank, boosted)
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
    async with SessionLocal() as session:
        rows = (await session.execute(stmt)).all()

    by_theme: dict[str, list[dict]] = {}
    total = 0
    for raw, proc, src_count, _rank, _boost in rows:
        theme = proc.theme or "noticia_relevante"
        bucket = by_theme.setdefault(theme, [])
        if len(bucket) >= per_theme:
            continue
        bucket.append(
            {
                "title": raw.title,
                "url": raw.url,
                "score": proc.importance_score,
                "tier": proc.importance_tier or "baja",
                "sources": int(src_count) if src_count else 1,
                "summary": proc.cleaned_summary,
                "published_at": raw.published_at,
            }
        )
        total += 1
    return by_theme, total


def _render(by_theme: dict[str, list[dict]], total: int) -> str:
    updated = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    cards = []
    for theme in THEME_ORDER:
        items = by_theme.get(theme)
        if not items:
            continue
        emoji = _THEME_EMOJI.get(theme, "🌐")
        cards.append(f'<h2>{emoji} {_esc(THEME_LABEL.get(theme, theme))}</h2>')
        for it in items:
            nota = f"{it['score']}/100" if it["score"] is not None else it["tier"]
            srcb = f'<span class="src">📡 {it["sources"]}</span>' if it["sources"] > 1 else ""
            date = it["published_at"].strftime("%d/%m") if it["published_at"] else ""
            title = _esc((it["title"] or "(sin título)"))
            link = f'<a href="{_esc(it["url"])}" target="_blank" rel="noopener">{title}</a>' if it["url"] else title
            summary = f'<p class="sum">{_esc(it["summary"])}</p>' if it["summary"] else ""
            cards.append(
                f'<div class="card"><div class="meta"><span class="nota">{_esc(nota)}</span>'
                f'{srcb}<span class="date">{date}</span></div>'
                f'<div class="title">{link}</div>{summary}</div>'
            )
    body = "\n".join(cards) or '<p class="empty">Sin noticias en los últimos 7 días.</p>'
    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI News — Briefing</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family:-apple-system,Segoe UI,system-ui,sans-serif; background:#0d1117; color:#e6edf3;
         margin:0; padding:24px; max-width:820px; margin:0 auto; }}
  h1 {{ font-size:24px; margin:0 0 2px; }}
  .sub {{ color:#8b949e; font-size:13px; margin-bottom:24px; }}
  h2 {{ font-size:17px; margin:26px 0 10px; padding-bottom:6px; border-bottom:1px solid #30363d; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px 14px; margin-bottom:10px; }}
  .title a {{ color:#58a6ff; text-decoration:none; font-weight:600; font-size:15px; }}
  .title a:hover {{ text-decoration:underline; }}
  .meta {{ display:flex; gap:10px; align-items:center; margin-bottom:6px; font-size:12px; color:#8b949e; }}
  .nota {{ background:#bc8cff33; color:#d2a8ff; padding:1px 8px; border-radius:10px; font-weight:600; }}
  .src {{ background:#3fb95033; color:#7ee787; padding:1px 8px; border-radius:10px; }}
  .sum {{ color:#c9d1d9; font-size:13px; line-height:1.5; margin:8px 0 0; }}
  .empty {{ color:#8b949e; }}
  footer {{ color:#8b949e; font-size:12px; margin-top:30px; border-top:1px solid #30363d; padding-top:12px; }}
</style></head><body>
<h1>📰 AI News — Briefing</h1>
<div class="sub">{total} noticias · últimos 7 días · actualizado {updated}</div>
{body}
<footer>Generado automáticamente · dedup semántico + clasificación IA</footer>
</body></html>"""


async def main(out_path: str) -> None:
    by_theme, total = await _collect(hours=168, per_theme=30)
    html_doc = _render(by_theme, total)
    import os

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"wrote {out_path} ({total} stories)")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "site/index.html"
    asyncio.run(main(out))
