"""Weekly email digest.

Sends ONE email with the week's top stories (last 7 days), once a week
(Sunday morning via .github/workflows/weekly_email.yml). Read-only: reuses the
same data the web/Telegram use, links to the per-story web pages. No-op when not
configured.

Transport is plain SMTP so it works with any provider:
  - Gmail:  EMAIL_HOST=smtp.gmail.com  EMAIL_USER=<you>@gmail.com  EMAIL_PASSWORD=<App Password>
  - Resend: EMAIL_HOST=smtp.resend.com EMAIL_USER=resend          EMAIL_PASSWORD=<API key>
"""
from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.export.static_site import _PLAYER_LOGO, _THEME_EN, _collect, _esc, _site_home
from app.links import detail_url
from app.logging_config import configure_logging, get_logger

log = get_logger(__name__)


_GOLD = "#b0904c"
_INK = "#1a1815"
_MUTED = "#6b655c"
_SOFT = "#9a938a"


def _email_players(players: list[str] | None) -> str:
    """Inline player tags (gold) with logos — logos are enhancement (clients may block images)."""
    home = _site_home()
    out = []
    for p in (players or [])[:3]:
        logo = _PLAYER_LOGO.get(p)
        img = (
            f'<span style="display:inline-block;background:#1a1a17;border-radius:5px;padding:3px;'
            f'vertical-align:middle;margin-right:5px;">'
            f'<img src="{home}/assets/players/{logo}" width="14" height="14" '
            f'style="display:block;border-radius:2px;" alt=""></span>'
        ) if logo else ""
        out.append(f'<span style="color:{_GOLD};font-weight:700;">{img}{_esc(p)}</span>')
    return " &nbsp;·&nbsp; ".join(out)


def _meta_line(it: dict) -> str:
    emoji, label = _THEME_EN.get(it["theme"], ("🌐", "Other"))
    score = it["relevance"] or it["score"] or 0
    srcs = f' &nbsp;·&nbsp; 📡 {it["sources"]} fuentes' if it["sources"] > 1 else ""
    return (
        f'<span style="text-transform:uppercase;letter-spacing:.08em;">{emoji} {label}</span>'
        f' &nbsp;·&nbsp; <span style="color:{_GOLD};font-weight:700;">{score}/100</span>{srcs}'
    )


def _render_email(items: list[dict]) -> str:
    """Magazine-style newsletter (Spicy4Tuna structure) in our dark + gold brand:
    dark wordmark banner, gold title, this-week teaser, a featured story with hero
    image, then the rest as a clean list. Email-safe (tables + inline styles)."""
    home = _site_home()
    week = datetime.now(timezone.utc).strftime("%d %b %Y")
    feat = items[0] if items else None
    rest = items[1:]

    tg_url = settings.telegram_channel_url
    tg_cta = (
        '<tr><td style="padding:12px 0 0;text-align:center;">'
        f'<a href="{tg_url}" style="background:{_GOLD};color:#1a1815;font:700 13px/1 Arial,sans-serif;'
        'text-decoration:none;padding:12px 24px;border-radius:999px;display:inline-block;">'
        '✈️ Únete en Telegram →</a></td></tr>'
    ) if tg_url else ""
    unsub_to = settings.email_from or settings.email_user or ""
    unsub = f"mailto:{unsub_to}?subject=Baja" if unsub_to else f"{home}/ai-news/"
    addr = f' &nbsp;·&nbsp; {_esc(settings.email_address)}' if settings.email_address else ""
    preheader = f"{len(items)} noticias de IA de la semana — filtradas, deduplicadas y resumidas."

    # This-week teaser — top headlines as quick bullets.
    teaser = "".join(
        f'<li style="margin:0 0 8px;"><a href="{detail_url(it["url"])}" '
        f'style="color:{_INK};text-decoration:none;font-weight:600;">{_esc(it["title"])}</a></li>'
        for it in items
    )

    # Featured story (top of the week).
    featured = ""
    if feat:
        img = feat.get("image_url")
        hero = (
            f'<tr><td style="padding:0 0 16px;"><img src="{_esc(img)}" width="536" '
            f'style="display:block;width:100%;max-width:536px;height:auto;border-radius:14px;" alt=""></td></tr>'
        ) if img else ""
        featured = f"""
    <tr><td style="padding:8px 0 4px;font:700 12px/1 Arial,sans-serif;color:{_SOFT};letter-spacing:.1em;text-transform:uppercase;">★ Destacado</td></tr>
    <tr><td style="padding:0 0 10px;font:13px/1 Arial,sans-serif;color:{_MUTED};">{_meta_line(feat)}</td></tr>
    <tr><td style="padding:0 0 14px;"><a href="{detail_url(feat["url"])}" style="font:700 24px/1.3 Arial,sans-serif;color:{_INK};text-decoration:none;letter-spacing:-.01em;">{_esc(feat["title"])}</a></td></tr>
    {hero}
    <tr><td style="padding:0 0 6px;font:300 15px/1.65 Arial,sans-serif;color:{_MUTED};">{_esc((feat["summary"] or "")[:360])}</td></tr>
    <tr><td style="padding:6px 0 0;">{_email_players(feat.get("players"))}</td></tr>
    <tr><td style="padding:16px 0 0;"><a href="{detail_url(feat["url"])}" style="background:{_GOLD};color:#fff;font:700 13px/1 Arial,sans-serif;text-decoration:none;padding:12px 22px;border-radius:999px;display:inline-block;">Leer en la web →</a></td></tr>
    <tr><td style="padding:26px 0;"><div style="height:1px;background:#e8e4d8;"></div></td></tr>"""

    # The rest — clean list.
    rows = []
    for it in rest:
        rows.append(f"""
    <tr><td style="padding:16px 0;border-bottom:1px solid #ece8dc;">
      <div style="font:12px/1 Arial,sans-serif;color:{_MUTED};margin-bottom:7px;">{_meta_line(it)}</div>
      <a href="{detail_url(it["url"])}" style="font:700 17px/1.35 Arial,sans-serif;color:{_INK};text-decoration:none;">{_esc(it["title"])}</a>
      <p style="font:300 14px/1.6 Arial,sans-serif;color:{_MUTED};margin:7px 0 0;">{_esc((it["summary"] or "")[:200])}</p>
      <div style="margin-top:8px;font:12px/1 Arial,sans-serif;">{_email_players(it.get("players"))}
        <a href="{detail_url(it["url"])}" style="color:{_GOLD};font-weight:700;text-decoration:none;float:right;">Leer →</a></div>
    </td></tr>""")
    rest_block = (
        f'<tr><td style="padding:8px 0 2px;font:700 13px/1 Arial,sans-serif;color:{_GOLD};letter-spacing:.06em;text-transform:uppercase;">Más esta semana</td></tr>'
        + "".join(rows)
    ) if rows else ""

    empty = "" if items else f'<tr><td style="padding:24px 0;color:{_MUTED};font:14px Arial;">No news this week.</td></tr>'

    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#e9e7e1;padding:0;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#e9e7e1;font-size:1px;line-height:1px;">{preheader}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#e9e7e1;">
<tr><td align="center" style="padding:26px 14px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:18px;">
   <tr><td style="padding:26px 26px 30px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="right" style="font:12px Arial,sans-serif;color:{_SOFT};padding:0 0 14px;">
      {week} &nbsp;|&nbsp; <a href="{home}/ai-news/" style="color:{_GOLD};text-decoration:none;">Ver online →</a>
    </td></tr>
    <tr><td style="background:#0d0d0d;border-radius:16px;padding:30px 24px;text-align:center;">
      <div style="font:800 30px/1 Arial,sans-serif;color:#ECEAE3;letter-spacing:-.02em;">AI <span style="color:#e2ba6b;">News</span></div>
      <div style="font:700 11px/1 Arial,sans-serif;color:#9a938a;letter-spacing:.22em;text-transform:uppercase;margin-top:10px;">Resumen semanal · {len(items)} noticias</div>
    </td></tr>
    <tr><td style="padding:24px 0 4px;font:700 22px/1.25 Arial,sans-serif;color:{_INK};letter-spacing:-.01em;">La semana en IA, sin ruido 🗞️</td></tr>
    <tr><td style="padding:0 0 14px;font:300 15px/1.6 Arial,sans-serif;color:{_MUTED};">{len(items)} historias filtradas, deduplicadas y resumidas — lo importante de la semana.</td></tr>
    <tr><td style="padding:4px 0 18px;"><ul style="margin:0;padding:0 0 0 18px;font:14px/1.5 Arial,sans-serif;color:{_INK};">{teaser}</ul></td></tr>
    <tr><td style="padding:0 0 22px;"><div style="height:2px;background:{_GOLD};width:48px;"></div></td></tr>
    {featured}{rest_block}{empty}
    <tr><td style="padding:28px 0 0;text-align:center;">
      <a href="{home}/ai-news/" style="background:#0d0d0d;color:#e2ba6b;font:700 13px/1 Arial,sans-serif;text-decoration:none;padding:12px 24px;border-radius:999px;display:inline-block;">Ver todo en la web →</a>
    </td></tr>
    {tg_cta}
    <tr><td style="padding:22px 0 0;text-align:center;font:12px/1.6 Arial,sans-serif;color:{_SOFT};">
      Recopilado y deduplicado con IA · el score (0–100) mide la relevancia editorial<br>
      <a href="{home}/" style="color:{_GOLD};text-decoration:none;">Manuel Mesonero</a> · AI News{addr}<br>
      Semanal · cada domingo · <a href="{unsub}" style="color:{_SOFT};text-decoration:underline;">Darse de baja</a>
    </td></tr>
    </table>
   </td></tr>
  </table>
</td></tr></table></body></html>"""


_MIN_STORIES = 10  # curated default: the week's top 10...


async def _gather() -> list[dict]:
    # Last 7 days, relevant only (exclude 'baja'), ordered by boosted score.
    # Curated: the top 5, PLUS any extra high-importance ('alta') story beyond the
    # top 5 so a busy week isn't cut short. Capped at email_max_items.
    items = await _collect(hours=168, limit=80)
    items = [it for it in items if (it.get("tier") or "media") != "baja"]
    extra_alta = [it for it in items[_MIN_STORIES:] if it.get("tier") == "alta"]
    return (items[:_MIN_STORIES] + extra_alta)[: settings.email_max_items]


async def send_weekly_digest() -> int:
    if not (settings.email_host and settings.email_user and settings.email_to):
        log.info("email.not_configured")
        return 0
    items = await _gather()
    if not items:
        log.info("email.no_stories")
        return 0

    recipients = [r.strip() for r in settings.email_to.split(",") if r.strip()]
    sender = settings.email_from or settings.email_user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🗞️ AI News · {len(items)} noticias de la semana"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    # Standard one-click/list unsubscribe (mailto) — improves deliverability.
    msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=Unsubscribe>"
    msg.attach(MIMEText("Abre este correo en un cliente compatible con HTML.", "plain"))
    msg.attach(MIMEText(_render_email(items), "html"))

    try:
        with smtplib.SMTP(settings.email_host, settings.email_port, timeout=30) as s:
            s.starttls()
            s.login(settings.email_user, settings.email_password)
            s.sendmail(msg["From"], recipients, msg.as_string())
        log.info("email.sent", recipients=len(recipients), stories=len(items))
        return len(items)
    except Exception as e:
        log.warning("email.failed", err=str(e)[:200])
        return 0


def main() -> None:
    configure_logging()
    asyncio.run(send_weekly_digest())


if __name__ == "__main__":
    main()
