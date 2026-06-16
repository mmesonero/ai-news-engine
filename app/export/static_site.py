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
from app.config import settings
from app.database import SessionLocal
from app.links import detail_path, story_slug


def _site_home() -> str:
    base = settings.public_site_base.rstrip("/")
    return base[:-len("/ai-news")] if base.endswith("/ai-news") else base


def _nav() -> str:
    home = _site_home()
    return (
        '<nav class="nav"><div class="container nav-inner">'
        f'<a href="{home}/" class="brand" aria-label="Manuel Mesonero">'
        f'<img src="{home}/assets/logo.png" alt="Manuel Mesonero" class="brand-mark"></a>'
        '<div class="nav-links">'
        f'<a href="{home}/#work">Work</a><span class="nav-sep">·</span>'
        f'<a href="{home}/#progress">In Progress</a><span class="nav-sep">·</span>'
        f'<a href="{home}/#about">About Me</a><span class="nav-sep">·</span>'
        f'<a href="{home}/ai-news/" class="nav-accent">AI News</a>'
        "</div></div></nav>"
    )
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.models.source import Source

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

# Short labels for the compact landing UI (full labels stay for Telegram/briefing).
_SHORT_LABEL = {
    "nuevo_modelo": "Modelos",
    "herramienta_nueva": "Herramientas",
    "nueva_funcionalidad": "Funciones",
    "movimiento_empresarial": "Negocio",
    "caso_practico": "Casos",
    "insight_negocio": "Insights",
    "ejemplo_uso": "Tutoriales",
    "noticia_relevante": "Otras",
}


def _esc(s: str | None) -> str:
    return html.escape(s or "")


_FONT = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">'
)

# Shared CSS (plain string, single braces). Used by index + detail pages.
_STYLE = """
  :root {
    --bg:#FAFAF7; --bg-elev:#FFFFFF; --bg-muted:#F2F0E9;
    --text:#1A1815; --text-muted:#6B655C; --text-soft:#9A938A;
    --border:rgba(26,24,21,0.10); --border-strong:rgba(26,24,21,0.18);
    --accent:#C8A864; --accent-soft:rgba(200,168,100,0.14); --accent-strong:#B0904C;
    --shadow-sm:0 1px 2px rgba(26,24,21,0.04);
    --shadow-md:0 8px 24px -8px rgba(26,24,21,0.10), 0 2px 6px rgba(26,24,21,0.05);
    --sans:'Outfit','Inter',-apple-system,BlinkMacSystemFont,sans-serif;
    --mono:'Outfit','Inter',-apple-system,BlinkMacSystemFont,sans-serif;
    --radius-sm:8px; --radius-md:14px; --container:1180px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#1A1A17; --bg-elev:#22221E; --bg-muted:#22221E;
      --text:#ECEAE3; --text-muted:#9A938A; --text-soft:#6B655C;
      --border:rgba(236,234,227,0.08); --border-strong:rgba(236,234,227,0.16);
      --accent:#D4B775; --accent-soft:rgba(212,183,117,0.12); --accent-strong:#E2C589;
      --shadow-sm:0 1px 2px rgba(0,0,0,0.30);
      --shadow-md:0 10px 30px -10px rgba(0,0,0,0.55), 0 2px 6px rgba(0,0,0,0.30);
    }
  }
  * { box-sizing:border-box; }
  body { font-family:var(--sans); background:var(--bg); color:var(--text);
         margin:0; padding:0; font-weight:400; line-height:1.55;
         -webkit-font-smoothing:antialiased; }
  .wrap { max-width:760px; margin:0 auto; padding:40px 22px 64px; }
  /* nav (matches mmesonero.github.io) */
  .container { max-width:var(--container); margin:0 auto; padding:0 32px; }
  .nav { position:sticky; top:0; z-index:50; backdrop-filter:blur(14px) saturate(1.2);
         -webkit-backdrop-filter:blur(14px) saturate(1.2);
         background:color-mix(in oklab, var(--bg) 78%, transparent);
         border-bottom:1px solid transparent; }
  .nav-inner { display:flex; align-items:center; justify-content:center; height:72px; gap:32px; }
  .brand { display:flex; align-items:center; }
  .brand-mark { height:42px; width:auto; display:block; transition:transform .4s; }
  .brand:hover .brand-mark { transform:scale(1.04); }
  .nav-links { display:flex; gap:18px; font-size:12px; font-weight:400; font-family:var(--mono);
               letter-spacing:0.22em; text-transform:uppercase; color:var(--text-muted); align-items:center; }
  .nav-links a { position:relative; text-decoration:none; color:var(--text-muted); white-space:nowrap; transition:color .2s ease; }
  .nav-links a:hover { color:var(--text); }
  .nav-sep { color:var(--text-soft); font-family:var(--mono); font-size:11px; }
  .nav-accent { color:var(--accent) !important; }
  .nav-accent:hover { color:var(--accent-strong) !important; }
  @media (max-width:640px) { .nav-links { gap:10px; font-size:10px; letter-spacing:0.16em; } .nav-sep { font-size:9px; } .brand-mark { height:34px; } .container { padding:0 22px; } }
  header { margin-bottom:22px; }
  h1 { font-family:var(--sans); font-weight:600; font-size:34px; letter-spacing:-0.02em; margin:0 0 6px; }
  .sub { color:var(--text-muted); font-size:14px; }
  .accent { color:var(--accent-strong); }
  .controls { display:flex; flex-direction:column; gap:10px; margin:22px 0 26px; }
  .ctrl-row { display:flex; gap:9px; flex-wrap:wrap; align-items:center; }
  .ctrl-label { font-size:12px; font-weight:600; color:var(--text-soft); text-transform:uppercase; letter-spacing:0.04em; }
  select { font-family:var(--sans); font-size:13px; font-weight:500; color:var(--text);
           background:var(--bg-elev); border:1px solid var(--border-strong); border-radius:999px;
           padding:7px 13px; cursor:pointer; }
  select:hover { border-color:var(--accent-strong); }
  .switch { display:inline-flex; align-items:center; gap:8px; cursor:pointer;
            font-size:13px; font-weight:500; color:var(--text-muted); margin-left:auto; user-select:none; }
  .switch input { position:absolute; opacity:0; pointer-events:none; }
  .switch .track { width:40px; height:23px; border-radius:999px; background:var(--border-strong);
                   position:relative; transition:background .2s; flex:none; }
  .switch .track::after { content:""; position:absolute; top:2.5px; left:2.5px; width:18px; height:18px;
                          border-radius:50%; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.3); transition:transform .2s; }
  .switch input:checked + .track { background:var(--accent-strong); }
  .switch input:checked + .track::after { transform:translateX(17px); }
  .card { background:var(--bg-elev); border:1px solid var(--border); border-radius:var(--radius-md);
          padding:16px 18px; margin-bottom:12px; box-shadow:var(--shadow-sm); transition:box-shadow .2s,border-color .2s; }
  .card:hover { box-shadow:var(--shadow-md); border-color:var(--border-strong); }
  .card.hide { display:none; }
  .meta { display:flex; gap:9px; align-items:center; margin-bottom:8px; font-size:12px; color:var(--text-soft); flex-wrap:wrap; }
  .tag { font-weight:500; color:var(--text-muted); }
  .nota { background:var(--accent-soft); color:var(--accent-strong); padding:2px 9px; border-radius:999px; font-weight:600; }
  .src { border:1px solid var(--border-strong); padding:2px 9px; border-radius:999px; }
  .date { margin-left:auto; }
  .title a { color:var(--text); text-decoration:none; font-weight:500; font-size:17px; line-height:1.35; }
  .title a:hover { color:var(--accent-strong); }
  .sum { color:var(--text-muted); font-size:14px; margin:9px 0 0; font-weight:300; }
  .empty { color:var(--text-muted); }
  footer { color:var(--text-soft); font-size:12.5px; margin-top:44px; border-top:1px solid var(--border); padding-top:16px; }
  footer a { color:var(--accent-strong); text-decoration:none; }
  /* detail page */
  .back { display:inline-block; color:var(--text-soft); text-decoration:none; font-size:13px; margin-bottom:18px; }
  .back:hover { color:var(--accent-strong); }
  .detail-title { font-size:27px; font-weight:600; line-height:1.25; letter-spacing:-0.01em; margin:6px 0 14px; }
  .detail-sum { font-size:16px; color:var(--text-muted); line-height:1.6; font-weight:300; margin:0 0 24px; }
  .players { display:flex; gap:7px; flex-wrap:wrap; margin:18px 0; }
  .chip { background:var(--bg-muted); border:1px solid var(--border); color:var(--text-muted);
          padding:3px 11px; border-radius:999px; font-size:12.5px; font-weight:500; }
  .source-btn { display:inline-block; background:var(--accent-strong); color:#fff; text-decoration:none;
                font-weight:600; font-size:14px; padding:11px 20px; border-radius:999px; margin-top:8px; }
  .source-btn:hover { filter:brightness(1.06); }
  .hero { width:100%; max-height:360px; object-fit:cover; border-radius:var(--radius-md);
          border:1px solid var(--border); margin:6px 0 20px; display:block; }
  .sources-label { font-size:12px; font-weight:600; color:var(--text-soft); text-transform:uppercase;
                   letter-spacing:0.04em; margin:24px 0 8px; }
  .sources-row { display:flex; gap:8px; flex-wrap:wrap; }
  .source-chip { display:inline-flex; align-items:center; gap:5px; text-decoration:none;
                 background:var(--bg-elev); border:1px solid var(--border-strong); color:var(--text);
                 font-size:13px; font-weight:500; padding:7px 13px; border-radius:999px; transition:border-color .2s,color .2s; }
  .source-chip:hover { border-color:var(--accent-strong); color:var(--accent-strong); }
"""


async def _collect(hours: int, limit: int) -> list[dict]:
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
    src = func.coalesce(stats_subq.c.sources, 1)
    boosted = (func.coalesce(ProcessedContent.importance_score, 0) + func.least(20, (src - 1) * 8)).label("boosted")
    rep_subq = select(ContentCluster.representative_content_id)

    stmt = (
        select(RawContent, ProcessedContent, src.label("sources"), tier_rank, boosted)
        .join(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .outerjoin(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
        .outerjoin(stats_subq, stats_subq.c.cid == ClusterItem.cluster_id)
        # Show ALL non-noise stories (even those without a theme/tier from the old
        # classifier — they bucket under "Otras" and still appear).
        .where(ProcessedContent.is_noise.is_(False))
        .where(or_(ProcessedContent.theme.is_(None), ProcessedContent.theme != "irrelevante"))
        .where(or_(ClusterItem.cluster_id.is_(None), RawContent.id.in_(rep_subq)))
        .where(
            or_(
                RawContent.published_at >= since,
                (RawContent.published_at.is_(None)) & (RawContent.fetched_at >= since),
            )
        )
        .order_by(desc(boosted), desc(tier_rank), desc(RawContent.published_at))
        .limit(limit)
    )
    items: list[dict] = []
    async with SessionLocal() as session:
        rows = (await session.execute(stmt)).all()
        for raw, proc, src_count, _rank, boost in rows:
            when = raw.published_at or raw.fetched_at
            # Gather EVERY outlet that covered this story (one chip per source).
            cid = (
                await session.execute(
                    select(ClusterItem.cluster_id).where(ClusterItem.raw_content_id == raw.id)
                )
            ).scalar_one_or_none()
            sources_list: list[dict] = []
            if cid is not None:
                mem = await session.execute(
                    select(Source.name, RawContent.url, RawContent.id)
                    .join(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
                    .join(Source, Source.id == RawContent.source_id)
                    .where(ClusterItem.cluster_id == cid)
                )
                seen: set[str] = set()
                for name, url, rid in mem.all():
                    nm = name or "fuente"
                    if nm in seen:
                        continue
                    seen.add(nm)
                    # representative first
                    entry = {"name": nm, "url": url}
                    (sources_list.insert(0, entry) if rid == raw.id else sources_list.append(entry))
            if not sources_list:
                sname = (
                    await session.execute(select(Source.name).where(Source.id == raw.source_id))
                ).scalar_one_or_none()
                sources_list = [{"name": sname or "fuente", "url": raw.url}]

            items.append(
                {
                    "theme": proc.theme or "noticia_relevante",
                    "title": proc.title_es or raw.title,
                    "url": raw.url,
                    "score": proc.importance_score,
                    "tier": proc.importance_tier or "",  # "" → not treated as 'baja', shows by default
                    "sources": int(src_count) if src_count else 1,
                    "sources_list": sources_list,
                    "summary": proc.cleaned_summary,
                    "published_at": raw.published_at,
                    "ts": int(when.timestamp()) if when else 0,
                    "relevance": int(boost) if boost is not None else 0,
                    "players": proc.players or [],
                    "image_url": raw.image_url,
                }
            )
    return items


def _render(items: list[dict]) -> str:
    updated = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    total = len(items)
    # themes present, in canonical order, for the filter dropdown
    present = [t for t in THEME_ORDER if any(it["theme"] == t for it in items)]
    opts = '<option value="all">Todos los temas</option>' + "".join(
        f'<option value="{t}">{_THEME_EMOJI.get(t, "🌐")} {_esc(_SHORT_LABEL.get(t, t))}</option>'
        for t in present
    )
    # players present, by frequency
    pcount: dict[str, int] = {}
    for it in items:
        for p in it.get("players") or []:
            pcount[p] = pcount.get(p, 0) + 1
    players_present = sorted(pcount, key=lambda p: -pcount[p])
    no_player = sum(1 for it in items if not (it.get("players") or []))
    popts = '<option value="all">Todos los players</option>' + "".join(
        f'<option value="{_esc(p)}">{_esc(p)} ({pcount[p]})</option>' for p in players_present
    )
    if no_player:
        popts += f'<option value="__none__">Otros ({no_player})</option>'

    cards = []
    for it in items:
        theme = it["theme"]
        emoji = _THEME_EMOJI.get(theme, "🌐")
        label = _esc(_SHORT_LABEL.get(theme, theme))
        nota = f"{it['score']}/100" if it["score"] is not None else (it["tier"] or "—")
        srcb = f'<span class="src">📡 {it["sources"]}</span>' if it["sources"] > 1 else ""
        date = it["published_at"].strftime("%d/%m") if it["published_at"] else ""
        date_attr = it["published_at"].strftime("%Y%m%d") if it["published_at"] else "0"
        title = _esc(it["title"] or "(sin título)")
        # Link to OUR detail subpage (not the source). Source link lives inside it.
        link = f'<a href="{_esc(detail_path(it["url"]))}">{title}</a>'
        summary = f'<p class="sum">{_esc(it["summary"])}</p>' if it["summary"] else ""
        cards.append(
            f'<article class="card" data-theme="{theme}" data-rel="{it["relevance"]}" '
            f'data-date="{date_attr}" data-ts="{it["ts"]}" data-tier="{it["tier"]}" '
            f'data-players="{_esc("|".join(it.get("players") or []))}">'
            f'<div class="meta"><span class="tag">{emoji} {label}</span>'
            f'<span class="nota">{_esc(nota)}</span>{srcb}'
            f'<span class="date">{date}</span></div>'
            f'<div class="title">{link}</div>{summary}</article>'
        )
    body = "\n".join(cards) or '<p class="empty">Sin noticias en los últimos 7 días.</p>'
    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI News — Manuel Mesonero</title>
<meta name="description" content="Briefing diario de noticias de IA, deduplicado y clasificado automáticamente.">
{_FONT}
<style>{_STYLE}</style></head><body>
{_nav()}
<div class="wrap">
<header>
  <h1>AI <span class="accent">News</span></h1>
  <div class="sub"><span id="count">{total}</span> noticias · actualizado {updated}</div>
</header>
<div class="controls">
  <div class="ctrl-row">
    <select id="range" aria-label="Rango temporal">
      <option value="24">24h</option>
      <option value="72">72h</option>
      <option value="168">Semana</option>
      <option value="720" selected>Mes</option>
    </select>
    <select id="sort" aria-label="Orden">
      <option value="rel">↓ Relevancia</option>
      <option value="date">↓ Reciente</option>
    </select>
    <label class="switch">
      <input type="checkbox" id="showlow"><span class="track"></span>
      <span>Baja relevancia</span>
    </label>
  </div>
  <div class="ctrl-row">
    <span class="ctrl-label">Tema</span><select id="filter">{opts}</select>
    <span class="ctrl-label">Players</span><select id="player">{popts}</select>
  </div>
</div>
<div id="list">
{body}
</div>
<footer>Recopilado y clasificado automáticamente · dedup semántico + IA · <a href="{_site_home()}/">← mmesonero</a></footer>
</div>
<script>
(function() {{
  var list = document.getElementById('list');
  var rangeEl = document.getElementById('range');
  var filterEl = document.getElementById('filter');
  var playerEl = document.getElementById('player');
  var sortEl = document.getElementById('sort');
  var lowEl = document.getElementById('showlow');
  var countEl = document.getElementById('count');
  var cards = Array.prototype.slice.call(list.querySelectorAll('.card'));
  function apply() {{
    var f = filterEl.value, p = playerEl.value, s = sortEl.value, showLow = lowEl.checked;
    var hours = parseInt(rangeEl.value, 10);
    var cutoff = (Date.now() / 1000) - hours * 3600;
    var vis = cards.filter(function(c) {{
      if (f !== 'all' && c.dataset.theme !== f) return false;
      if (p === '__none__') {{ if (c.dataset.players) return false; }}
      else if (p !== 'all' && ('|' + c.dataset.players + '|').indexOf('|' + p + '|') === -1) return false;
      if (!showLow && c.dataset.tier === 'baja') return false;
      var ts = parseInt(c.dataset.ts, 10);
      return ts >= cutoff;
    }});
    cards.forEach(function(c) {{ c.classList.add('hide'); }});
    vis.sort(function(a, b) {{
      if (s === 'date') return parseInt(b.dataset.ts, 10) - parseInt(a.dataset.ts, 10);
      return parseInt(b.dataset.rel, 10) - parseInt(a.dataset.rel, 10);
    }});
    vis.forEach(function(c) {{ c.classList.remove('hide'); list.appendChild(c); }});
    countEl.textContent = vis.length;
  }}
  rangeEl.addEventListener('change', apply);
  filterEl.addEventListener('change', apply);
  playerEl.addEventListener('change', apply);
  sortEl.addEventListener('change', apply);
  lowEl.addEventListener('change', apply);
  apply();
}})();
</script>
</body></html>"""


def _render_detail(it: dict) -> str:
    theme = it["theme"]
    emoji = _THEME_EMOJI.get(theme, "🌐")
    label = _esc(_SHORT_LABEL.get(theme, theme))
    nota = f"{it['score']}/100" if it["score"] is not None else (it["tier"] or "—")
    srcb = f'<span class="src">📡 {it["sources"]} fuentes</span>' if it["sources"] > 1 else ""
    date = it["published_at"].strftime("%d/%m/%Y") if it["published_at"] else ""
    title = _esc(it["title"] or "(sin título)")
    summary = _esc(it["summary"]) if it["summary"] else "Sin resumen disponible."
    chips = "".join(f'<span class="chip">{_esc(p)}</span>' for p in (it.get("players") or []))
    chips_block = f'<div class="players">{chips}</div>' if chips else ""
    chips = "".join(
        f'<a class="source-chip" href="{_esc(s["url"])}" target="_blank" rel="noopener">↗ {_esc(s["name"])}</a>'
        for s in (it.get("sources_list") or []) if s.get("url")
    )
    source = (
        f'<div class="sources-label">Fuentes ({len(it.get("sources_list") or [])})</div>'
        f'<div class="sources-row">{chips}</div>'
    ) if chips else ""
    img = it.get("image_url")
    hero = f'<img class="hero" src="{_esc(img)}" alt="" loading="lazy">' if img else ""
    og_image = f'<meta property="og:image" content="{_esc(img)}">' if img else ""
    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — AI News</title>
<meta name="description" content="{_esc((it['summary'] or '')[:150])}">
<meta property="og:title" content="{title}">{og_image}
{_FONT}
<style>{_STYLE}</style></head><body>
{_nav()}
<div class="wrap">
  <a class="back" href="../index.html">← Volver a AI News</a>
  {hero}
  <div class="meta"><span class="tag">{emoji} {label}</span><span class="nota">{_esc(nota)}</span>{srcb}<span class="date">{date}</span></div>
  <h1 class="detail-title">{title}</h1>
  <p class="detail-sum">{summary}</p>
  {chips_block}
  {source}
  <footer>Resumen y clasificación automáticos · <a href="../index.html">← AI News</a></footer>
</div>
</body></html>"""


async def main(out_path: str) -> None:
    import os

    items = await _collect(hours=720, limit=200)  # bake 30 days; client filters by range
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    # index
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_render(items))
    # per-story detail pages under <out_dir>/n/<slug>.html
    n_dir = os.path.join(out_dir, "n")
    os.makedirs(n_dir, exist_ok=True)
    for it in items:
        slug = story_slug(it["url"])
        with open(os.path.join(n_dir, f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(_render_detail(it))
    print(f"wrote {out_path} + {len(items)} detail pages")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "site/index.html"
    asyncio.run(main(out))
