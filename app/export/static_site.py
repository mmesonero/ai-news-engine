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
import json
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, desc, func, or_, select

from app.api.v1.briefing import THEME_LABEL, THEME_ORDER
from app.config import settings
from app.database import SessionLocal
from app.links import detail_path, story_slug
from app.url_safety import safe_href


def _site_home() -> str:
    base = settings.public_site_base.rstrip("/")
    return base[:-len("/ai-news")] if base.endswith("/ai-news") else base


def _nav() -> str:
    # Copied verbatim from the AI News index topnav (logo + Portfolio · AI News).
    home = _site_home()
    return (
        '<nav class="topnav"><div class="topnav-inner">'
        f'<a href="{home}/" class="topnav-brand"><img src="{home}/assets/logo.png" alt="MM"></a>'
        '<div class="topnav-links">'
        f'<a href="{home}/">Portfolio</a>'
        '<span class="topnav-sep">·</span>'
        '<a class="active">AI News</a>'
        "</div></div></nav>"
    )
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.models.source import Source

_THEME_EMOJI = {
    "models": "🧠",
    "tools": "🛠️",
    "features": "✨",
    "business": "💼",
    "cases": "📈",
    "insights": "💡",
    "tutorials": "🧪",
    "other": "🌐",
}

# Map engine theme keys -> the portfolio index.html theme keys (THEMES array).
# The custom index uses shorter keys; anything unknown buckets under "other".
_INDEX_THEME = {
    "models": "models",
    "tools": "tools",
    "features": "features",
    "business": "business",
    "cases": "cases",
    "insights": "insights",
    "tutorials": "tutorials",
    "other": "other",
}

# Short labels for the compact landing UI (full labels stay for Telegram/briefing).
_SHORT_LABEL = {
    "models": "Models",
    "tools": "Tools",
    "features": "Features",
    "business": "Business",
    "cases": "Cases",
    "insights": "Insights",
    "tutorials": "Tutorials",
    "other": "Other",
}


# English theme label + emoji (matches the index THEMES), keyed by engine theme.
_THEME_EN = {
    "models": ("🧠", "Models"),
    "tools": ("🛠️", "Tools"),
    "features": ("✨", "Features"),
    "business": ("💼", "Business"),
    "cases": ("📈", "Cases"),
    "insights": ("💡", "Insights"),
    "tutorials": ("🧪", "Tutorials"),
    "other": ("🌐", "Other"),
}

# Player → logo filename (mirrors the index PLAYER_LOGO) + brand color for the dot fallback.
_PLAYER_LOGO = {
    "OpenAI": "openai.png", "Anthropic": "anthropic.png", "Google": "google.webp",
    "Meta": "meta.png", "NVIDIA": "nvidia.png", "Microsoft": "microsoft.png",
    "Amazon": "amazon.png", "Apple": "apple.png", "xAI": "xai.png", "Mistral": "mistral.png",
    "SpaceX": "spacex.png", "Cursor": "cursor.png", "Tesla": "tesla.png",
    "Perplexity": "perplexity.webp", "DeepSeek": "deepseek.png",
}
_PLAYER_COLOR = {
    "OpenAI": "#10A37F", "Anthropic": "#CC785C", "Google": "#4285F4", "Meta": "#0866FF",
    "NVIDIA": "#76B900", "Microsoft": "#00A4EF", "Amazon": "#FF9900", "Apple": "#6E6E73",
    "xAI": "#AAAAAA", "Mistral": "#FF7000", "SpaceX": "#005288", "Cursor": "#000000",
    "Tesla": "#CC0000", "Perplexity": "#20808D", "DeepSeek": "#4D6BFE",
}

_SRC_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M4.9 19.1a10 10 0 0 1 0-14.2"/>'
    '<path d="M7.8 16.2a6 6 0 0 1 0-8.4"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/>'
    '<path d="M16.2 7.8a6 6 0 0 1 0 8.4"/><path d="M19.1 4.9a10 10 0 0 1 0 14.2"/></svg>'
)


def _esc(s: str | None) -> str:
    return html.escape(s or "")


def _player_html(players: list[str] | None) -> str:
    home = _site_home()
    parts = []
    for p in players or []:
        logo = _PLAYER_LOGO.get(p)
        if logo:
            inner = f'<img class="s-player-logo" src="{home}/assets/players/{logo}" alt="{_esc(p)}">'
        else:
            inner = f'<span class="s-player-dot" style="background:{_PLAYER_COLOR.get(p, "var(--text-soft)")}"></span>'
        parts.append(f'<span class="s-player">{inner}{_esc(p)}</span>')
    return f'<span class="s-players">{"".join(parts)}</span>' if parts else ""


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
      --bg:#0D0D0D; --bg-elev:#1A1A17; --bg-muted:#242420;
      --text:#ECEAE3; --text-muted:#9A938A; --text-soft:#6B655C;
      --border:rgba(236,234,227,0.08); --border-strong:rgba(236,234,227,0.16);
      --accent:#e2ba6b; --accent-soft:rgba(226,186,107,0.12); --accent-strong:#f0cc88;
      --shadow-sm:0 1px 2px rgba(0,0,0,0.30);
      --shadow-md:0 14px 34px -16px rgba(0,0,0,0.6), 0 2px 6px rgba(0,0,0,0.30);
    }
  }
  * { box-sizing:border-box; }
  body { font-family:var(--sans); background:var(--bg); color:var(--text);
         margin:0; padding:0; font-weight:400; line-height:1.55;
         -webkit-font-smoothing:antialiased; min-height:100vh; }
  /* background — copied verbatim from the AI News index (glows + vignette + grain) */
  body::before { content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
    background-image:
      radial-gradient(ellipse 900px 700px at 12% 8%, rgba(200,168,100,0.07), transparent 60%),
      radial-gradient(ellipse 800px 600px at 88% 82%, rgba(200,168,100,0.06), transparent 60%),
      radial-gradient(ellipse 1400px 900px at 50% 50%, transparent 0%, rgba(26,24,21,0.03) 80%); }
  body::after { content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
    opacity:0.45; mix-blend-mode:multiply;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.10  0 0 0 0 0.09  0 0 0 0 0.08  0 0 0 0.6 0'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.30'/></svg>");
    background-size:240px 240px; }
  @media (prefers-color-scheme: dark) {
    body::before { background-image:
      radial-gradient(ellipse 900px 700px at 12% 8%, rgba(226,186,107,0.06), transparent 60%),
      radial-gradient(ellipse 800px 600px at 88% 82%, rgba(226,186,107,0.05), transparent 60%),
      radial-gradient(ellipse 1400px 900px at 50% 50%, transparent 0%, rgba(0,0,0,0.35) 90%); }
    body::after { opacity:0.55; mix-blend-mode:screen;
      background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.95  0 0 0 0 0.93  0 0 0 0 0.88  0 0 0 0.5 0'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.16'/></svg>"); }
  }
  .topnav, .wrap { position:relative; z-index:1; }
  .wrap { max-width:760px; margin:0 auto; padding:40px 22px 64px; }
  /* top nav — copied verbatim from the AI News index */
  .topnav { position:sticky; top:0; z-index:50;
    backdrop-filter:blur(14px) saturate(1.2); -webkit-backdrop-filter:blur(14px) saturate(1.2);
    background:color-mix(in oklab, var(--bg) 78%, transparent);
    border-bottom:1px solid transparent; transition:border-color .25s ease;
    padding:0 clamp(24px, 6vw, 160px); }
  .topnav-inner { max-width:1200px; margin:0 auto; display:flex; align-items:center; justify-content:center; height:72px; gap:32px; }
  .topnav-brand { display:flex; align-items:center; }
  .topnav-brand img { height:36px; width:auto; opacity:.85; transition:transform .4s cubic-bezier(.2,.7,.2,1), opacity .3s ease; }
  .topnav-brand:hover img { transform:scale(1.04); opacity:1; }
  .topnav-links { display:flex; gap:18px; align-items:center; font-size:12px; font-weight:400; letter-spacing:0.22em; text-transform:uppercase; color:var(--text-muted); }
  .topnav-links a { color:var(--text-muted); text-decoration:none; transition:color .2s ease; position:relative; }
  .topnav-links a:hover { color:var(--text); }
  .topnav-links a::after { content:''; position:absolute; left:0; right:0; bottom:-6px; height:1px; background:var(--accent); transform:scaleX(0); transform-origin:left; transition:transform .35s cubic-bezier(.2,.7,.2,1); }
  .topnav-links a:hover::after { transform:scaleX(1); }
  .topnav-links .active { color:var(--accent); }
  .topnav-sep { color:var(--text-soft); font-size:11px; }
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
  /* index-style header chrome (matches the listing cards) */
  .s-tags { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:2px 0 6px; }
  .s-theme { display:inline-flex; align-items:center; gap:6px; font-size:11.5px; font-weight:500; color:var(--text-muted); }
  .s-theme .em { font-size:12px; }
  .s-players { display:inline-flex; align-items:center; gap:6px; }
  .s-player { font-size:11.5px; font-weight:500; color:var(--accent-strong); display:inline-flex; align-items:center; gap:5px; }
  .s-player-logo { width:14px; height:14px; border-radius:3px; object-fit:contain; flex-shrink:0; }
  .s-player-dot { width:7px; height:7px; border-radius:50%; flex-shrink:0; display:inline-block; }
  .s-player + .s-player::before { content:'·'; margin-right:6px; color:var(--text-soft); }
  .s-score { flex:0 0 auto; width:40px; height:40px; border-radius:50%; display:grid; place-items:center;
             position:relative; margin-left:auto;
             background:conic-gradient(var(--ring) calc(var(--v)*1%), var(--track) 0); --track:var(--border); --ring:var(--accent); }
  .s-score::before { content:''; position:absolute; inset:3px; border-radius:50%; background:var(--bg); }
  .s-score b { position:relative; font-size:12px; font-weight:600; color:var(--text); letter-spacing:-0.02em; }
  .s-tags[data-level="high"] .s-score { --ring:var(--accent-strong); }
  .s-tags[data-level="medium"] .s-score { --ring:var(--accent); }
  .s-tags[data-level="low"] .s-score { --ring:var(--text-soft); }
  .s-foot { display:flex; align-items:center; gap:10px; margin:16px 0 0; font-size:12.5px; color:var(--text-soft); flex-wrap:wrap; }
  .s-foot .dot { width:2.5px; height:2.5px; border-radius:50%; background:var(--text-soft); opacity:.7; }
  .s-foot .s-src { display:inline-flex; align-items:center; gap:6px; }
  .s-foot .s-src svg { width:12px; height:12px; opacity:.8; }
"""


async def _collect(hours: int, limit: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    tier_rank = case(
        (ProcessedContent.importance_tier == "high", 3),
        (ProcessedContent.importance_tier == "medium", 2),
        (ProcessedContent.importance_tier == "low", 1),
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
        .where(or_(ProcessedContent.theme.is_(None), ProcessedContent.theme != "irrelevant"))
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

        # Batch what used to be 2 queries PER row (N+1 → a constant 3 queries):
        # 1) representative id -> its cluster id
        rep_ids = [raw.id for raw, *_ in rows]
        cid_by_rep: dict[int, int] = {}
        if rep_ids:
            cid_rows = await session.execute(
                select(ClusterItem.raw_content_id, ClusterItem.cluster_id).where(
                    ClusterItem.raw_content_id.in_(rep_ids)
                )
            )
            cid_by_rep = {rid: cid for rid, cid in cid_rows.all()}
        # 2) cluster id -> all member (name, url, raw_id) rows, in one query
        cids = list({c for c in cid_by_rep.values()})
        members_by_cid: dict[int, list[tuple]] = {}
        if cids:
            mem_rows = await session.execute(
                select(ClusterItem.cluster_id, Source.name, RawContent.url, RawContent.id)
                .join(RawContent, RawContent.id == ClusterItem.raw_content_id)
                .join(Source, Source.id == RawContent.source_id)
                .where(ClusterItem.cluster_id.in_(cids))
            )
            for cid_, name, url, rid in mem_rows.all():
                members_by_cid.setdefault(cid_, []).append((name, url, rid))
        # 3) fallback source names for rows that aren't clustered, in one query
        fallback_ids = [raw.source_id for raw, *_ in rows if cid_by_rep.get(raw.id) is None]
        src_name_by_id: dict[int, str] = {}
        if fallback_ids:
            sn_rows = await session.execute(
                select(Source.id, Source.name).where(Source.id.in_(fallback_ids))
            )
            src_name_by_id = {sid: nm for sid, nm in sn_rows.all()}

        for raw, proc, src_count, _rank, boost in rows:
            when = raw.published_at or raw.fetched_at
            # Gather EVERY outlet that covered this story (one chip per source).
            cid = cid_by_rep.get(raw.id)
            sources_list: list[dict] = []
            if cid is not None:
                seen: set[str] = set()
                for name, url, rid in members_by_cid.get(cid, []):
                    nm = name or "source"
                    if nm in seen:
                        continue
                    seen.add(nm)
                    # representative first
                    entry = {"name": nm, "url": url}
                    (sources_list.insert(0, entry) if rid == raw.id else sources_list.append(entry))
            if not sources_list:
                sname = src_name_by_id.get(raw.source_id)
                sources_list = [{"name": sname or "source", "url": raw.url}]

            items.append(
                {
                    "theme": proc.theme or "other",
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
    opts = '<option value="all">All themes</option>' + "".join(
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
    popts = '<option value="all">All players</option>' + "".join(
        f'<option value="{_esc(p)}">{_esc(p)} ({pcount[p]})</option>' for p in players_present
    )
    if no_player:
        popts += f'<option value="__none__">Other ({no_player})</option>'

    cards = []
    for it in items:
        theme = it["theme"]
        emoji = _THEME_EMOJI.get(theme, "🌐")
        label = _esc(_SHORT_LABEL.get(theme, theme))
        nota = f"{it['score']}/100" if it["score"] is not None else (it["tier"] or "—")
        srcb = f'<span class="src">📡 {it["sources"]}</span>' if it["sources"] > 1 else ""
        date = it["published_at"].strftime("%d/%m") if it["published_at"] else ""
        date_attr = it["published_at"].strftime("%Y%m%d") if it["published_at"] else "0"
        title = _esc(it["title"] or "(untitled)")
        # Link to OUR detail subpage (not the source). Source link lives inside it.
        link = f'<a href="{_esc(safe_href(detail_path(it["url"])))}">{title}</a>'
        summary = f'<p class="sum">{_esc(it["summary"])}</p>' if it["summary"] else ""
        cards.append(
            f'<article class="card" data-theme="{_esc(theme)}" data-rel="{it["relevance"]}" '
            f'data-date="{date_attr}" data-ts="{it["ts"]}" data-tier="{it["tier"]}" '
            f'data-players="{_esc("|".join(it.get("players") or []))}">'
            f'<div class="meta"><span class="tag">{emoji} {label}</span>'
            f'<span class="nota">{_esc(nota)}</span>{srcb}'
            f'<span class="date">{date}</span></div>'
            f'<div class="title">{link}</div>{summary}</article>'
        )
    body = "\n".join(cards) or '<p class="empty">No news in the last 7 days.</p>'
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI News — Manuel Mesonero</title>
<meta name="description" content="Daily AI news briefing, automatically deduplicated and classified.">
{_FONT}
<style>{_STYLE}</style></head><body>
{_nav()}
<div class="wrap">
<header>
  <h1>AI <span class="accent">News</span></h1>
  <div class="sub"><span id="count">{total}</span> stories · updated {updated}</div>
</header>
<div class="controls">
  <div class="ctrl-row">
    <select id="range" aria-label="Time range">
      <option value="24">24h</option>
      <option value="72">72h</option>
      <option value="168">Week</option>
      <option value="720" selected>Month</option>
    </select>
    <select id="sort" aria-label="Sort">
      <option value="rel">↓ Relevance</option>
      <option value="date">↓ Recent</option>
    </select>
    <label class="switch">
      <input type="checkbox" id="showlow"><span class="track"></span>
      <span>Low relevance</span>
    </label>
  </div>
  <div class="ctrl-row">
    <span class="ctrl-label">Theme</span><select id="filter">{opts}</select>
    <span class="ctrl-label">Players</span><select id="player">{popts}</select>
  </div>
</div>
<div id="list">
{body}
</div>
<footer>Auto-curated &amp; classified · semantic dedup + AI · <a href="{_site_home()}/">← mmesonero</a></footer>
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
    emoji, label = _THEME_EN.get(theme, ("🌐", "Other"))
    tier = it["tier"] or "medium"
    score = it["relevance"] or it["score"] or 0
    date = it["published_at"].strftime("%d %b %Y") if it["published_at"] else ""
    title = _esc(it["title"] or "(untitled)")
    summary = _esc(it["summary"]) if it["summary"] else "No summary available."
    players_html = _player_html(it.get("players"))
    n_src = it["sources"]
    src = (
        f'<span class="dot"></span><span class="s-src">{_SRC_ICON}{n_src} sources</span>'
        if n_src > 1 else ""
    )
    src_chips = "".join(
        f'<a class="source-chip" href="{_esc(safe_href(s["url"]))}" target="_blank" rel="noopener">↗ {_esc(s["name"])}</a>'
        for s in (it.get("sources_list") or []) if s.get("url")
    )
    source = (
        f'<div class="sources-label">Sources ({len(it.get("sources_list") or [])})</div>'
        f'<div class="sources-row">{src_chips}</div>'
    ) if src_chips else ""
    img = it.get("image_url")
    safe_img = safe_href(img) if img else ""
    hero = f'<img class="hero" src="{_esc(safe_img)}" alt="" loading="lazy">' if img else ""
    og_image = f'<meta property="og:image" content="{_esc(safe_img)}">' if img else ""
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
  <a class="back" href="../index.html">← Back to AI News</a>
  {hero}
  <div class="s-tags" data-level="{tier}">{players_html}<span class="s-theme"><span class="em">{emoji}</span>{label}</span><span class="s-score" style="--v:{score}"><b>{score}</b></span></div>
  <h1 class="detail-title">{title}</h1>
  <p class="detail-sum">{summary}</p>
  <div class="s-foot"><span>{date}</span>{src}</div>
  {source}
  <footer>Auto-summarized &amp; classified · <a href="../index.html">← AI News</a></footer>
</div>
</body></html>"""


def _data_payload(items: list[dict], now: int) -> dict:
    """Real news in the custom portfolio index.html schema (DATA array shape).
    The index renders this; `detail` is the per-story page Telegram also links to.
    `now` is shared across data.js + data-archive.js so relative dates line up."""
    data = []
    for it in items:
        ts = it["ts"] or now
        # safe_href on every URL that ends up in an href: the index renders these into
        # markup, and a feed-supplied `javascript:` URL is not neutralized by escaping.
        # This is scheme validation, not encoding — the consumer still escapes.
        urls = [
            {"label": s["name"], "href": safe_href(s["url"])}
            for s in (it.get("sources_list") or [])
            if s.get("url")
        ]
        data.append(
            {
                "title": it["title"] or "(untitled)",
                "detail": safe_href(detail_path(it["url"])),  # n/<slug>.html — click → detail
                "url": safe_href(it["url"]),
                "theme": _INDEX_THEME.get(it["theme"], "other"),
                "score": it["relevance"] or it["score"] or 0,  # cross-source boosted
                "level": it["tier"] or "medium",  # "" → media so it shows by default
                "sources": it["sources"],
                "players": it.get("players") or [],
                "ago": max(0, now - ts),
                "urls": urls,
                "sum": it["summary"] or "",
            }
        )
    return {"now": now, "data": data}


def _emit_data_js(items: list[dict], now: int) -> str:
    return "window.__NEWS = " + json.dumps(_data_payload(items, now), ensure_ascii=False) + ";\n"


def _emit_archive_js(items: list[dict], now: int) -> str:
    # Lazy-loaded by the index when the user picks "All" — older than the recent window.
    return "window.__NEWS_ARCHIVE = " + json.dumps(_data_payload(items, now), ensure_ascii=False) + ";\n"


# Stories newer than this go in data.js (fast default load); older go in data-archive.js
# (lazy-loaded on demand). The DB keeps metadata forever (archive-friendly retention).
RECENT_DAYS = 90


async def main(out_path: str) -> None:
    import os

    now = int(datetime.now(timezone.utc).timestamp())
    # Pull the whole archive; split into recent (data.js) + older (data-archive.js).
    all_items = await _collect(hours=24 * 3650, limit=5000)
    cut = now - RECENT_DAYS * 86400
    recent = [it for it in all_items if (it["ts"] or now) >= cut]
    archive = [it for it in all_items if (it["ts"] or now) < cut]

    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    # index (rendered from the recent set; client filters by range)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_render(recent))
    # data.js — recent news (window.__NEWS), loaded immediately by index.html
    with open(os.path.join(out_dir, "data.js"), "w", encoding="utf-8") as f:
        f.write(_emit_data_js(recent, now))
    # data-archive.js — older news (window.__NEWS_ARCHIVE), lazy-loaded on "All"
    with open(os.path.join(out_dir, "data-archive.js"), "w", encoding="utf-8") as f:
        f.write(_emit_archive_js(archive, now))
    # per-story detail pages for the WHOLE archive (recent + old)
    n_dir = os.path.join(out_dir, "n")
    os.makedirs(n_dir, exist_ok=True)
    for it in all_items:
        slug = story_slug(it["url"])
        with open(os.path.join(n_dir, f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(_render_detail(it))
    print(
        f"wrote {out_path} + data.js ({len(recent)}) + data-archive.js ({len(archive)}) "
        f"+ {len(all_items)} detail pages"
    )


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "site/index.html"
    asyncio.run(main(out))
