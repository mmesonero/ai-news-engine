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
<title>AI News — Manuel Mesonero</title>
<meta name="description" content="Briefing diario de noticias de IA, deduplicado y clasificado automáticamente.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Outfit:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#FAFAF7; --bg-elev:#FFFFFF; --bg-muted:#F2F0E9;
    --text:#1A1815; --text-muted:#6B655C; --text-soft:#9A938A;
    --border:rgba(26,24,21,0.10); --border-strong:rgba(26,24,21,0.18);
    --accent:#C8A864; --accent-soft:rgba(200,168,100,0.14); --accent-strong:#B0904C;
    --shadow-sm:0 1px 2px rgba(26,24,21,0.04);
    --shadow-md:0 8px 24px -8px rgba(26,24,21,0.10), 0 2px 6px rgba(26,24,21,0.05);
    --serif:'Cormorant Garamond',Georgia,serif;
    --sans:'Outfit','Inter',-apple-system,BlinkMacSystemFont,sans-serif;
    --radius-sm:8px; --radius-md:14px;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg:#1A1A17; --bg-elev:#22221E; --bg-muted:#22221E;
      --text:#ECEAE3; --text-muted:#9A938A; --text-soft:#6B655C;
      --border:rgba(236,234,227,0.08); --border-strong:rgba(236,234,227,0.16);
      --accent:#D4B775; --accent-soft:rgba(212,183,117,0.12); --accent-strong:#E2C589;
      --shadow-sm:0 1px 2px rgba(0,0,0,0.30);
      --shadow-md:0 10px 30px -10px rgba(0,0,0,0.55), 0 2px 6px rgba(0,0,0,0.30);
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:var(--sans); background:var(--bg); color:var(--text);
         margin:0; padding:48px 22px 64px; font-weight:300; line-height:1.55; }}
  .wrap {{ max-width:760px; margin:0 auto; }}
  header {{ margin-bottom:36px; }}
  h1 {{ font-family:var(--serif); font-weight:500; font-size:42px; letter-spacing:-0.01em;
       margin:0 0 6px; }}
  .sub {{ color:var(--text-muted); font-size:14px; }}
  .accent {{ color:var(--accent-strong); }}
  h2 {{ font-family:var(--serif); font-weight:600; font-size:25px; margin:38px 0 14px;
       display:flex; align-items:center; gap:10px; }}
  .card {{ background:var(--bg-elev); border:1px solid var(--border); border-radius:var(--radius-md);
          padding:16px 18px; margin-bottom:12px; box-shadow:var(--shadow-sm); transition:box-shadow .2s,border-color .2s; }}
  .card:hover {{ box-shadow:var(--shadow-md); border-color:var(--border-strong); }}
  .meta {{ display:flex; gap:10px; align-items:center; margin-bottom:7px; font-size:12px; color:var(--text-soft); }}
  .nota {{ background:var(--accent-soft); color:var(--accent-strong); padding:2px 9px;
          border-radius:999px; font-weight:600; letter-spacing:0.01em; }}
  .src {{ border:1px solid var(--border-strong); padding:2px 9px; border-radius:999px; }}
  .title a {{ color:var(--text); text-decoration:none; font-weight:500; font-size:17px; line-height:1.35; }}
  .title a:hover {{ color:var(--accent-strong); }}
  .sum {{ color:var(--text-muted); font-size:14px; margin:9px 0 0; }}
  .empty {{ color:var(--text-muted); }}
  footer {{ color:var(--text-soft); font-size:12.5px; margin-top:44px;
           border-top:1px solid var(--border); padding-top:16px; }}
  footer a {{ color:var(--accent-strong); text-decoration:none; }}
</style></head><body>
<div class="wrap">
<header>
  <h1>AI <span class="accent">News</span></h1>
  <div class="sub">{total} noticias · últimos 7 días · actualizado {updated}</div>
</header>
{body}
<footer>Recopilado y clasificado automáticamente · dedup semántico + IA · <a href="/">← mmesonero</a></footer>
</div>
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
