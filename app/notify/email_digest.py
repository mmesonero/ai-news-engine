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
from app.export.static_site import (
    _PLAYER_LOGO,
    _THEME_EN,
    _collect,
    _esc,
    _site_home,
)
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


def _clip(s: str | None, n: int = 600) -> str:
    """Trim a summary WITHOUT cutting mid-sentence: prefer the last sentence end,
    else the last word, + an ellipsis. Most summaries fit under n and show in full."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= int(n * 0.5):
        return cut[: end + 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut).rstrip(" ,;:") + "…"


def _meta_line(it: dict) -> str:
    emoji, label = _THEME_EN.get(it["theme"], ("🌐", "Other"))
    score = it["relevance"] or it["score"] or 0
    srcs = f' &nbsp;·&nbsp; 📡 {it["sources"]} sources' if it["sources"] > 1 else ""
    return (
        f'<span style="text-transform:uppercase;letter-spacing:.08em;">{emoji} {label}</span>'
        f' &nbsp;·&nbsp; <span style="color:{_GOLD};font-weight:700;">{score}/100</span>{srcs}'
    )


def _render_email(items: list[dict], unsub_href: str | None = None) -> str:
    """Magazine-style newsletter (Spicy4Tuna structure) in our dark + gold brand:
    dark wordmark banner, gold title, this-week teaser, a featured story with hero
    image, then the rest as a clean list. Email-safe (tables + inline styles).

    unsub_href: when sending via Brevo, pass "{{ unsubscribe }}" so Brevo injects its
    compliant 1-click unsubscribe URL; SMTP path falls back to a mailto link."""
    home = _site_home()
    week = datetime.now(timezone.utc).strftime("%d %b %Y")

    tg_url = settings.telegram_channel_url
    tg_cta = (
        '<tr><td style="padding:12px 0 0;text-align:center;">'
        f'<a href="{tg_url}" style="background:#2AABEE;color:#ffffff;font:700 13px/1 Arial,sans-serif;'
        'text-decoration:none;padding:12px 24px;border-radius:999px;display:inline-block;">'
        '📣 Join us on Telegram →</a></td></tr>'
    ) if tg_url else ""
    unsub_to = settings.email_from or settings.email_user or ""
    unsub = unsub_href or (f"mailto:{unsub_to}?subject=Unsubscribe" if unsub_to else f"{home}/ai-news/")
    addr = f' &nbsp;·&nbsp; {_esc(settings.email_address)}' if settings.email_address else ""
    preheader = f"{len(items)} AI stories this week — filtered, deduplicated and summarized."

    # Uniform cards — EVERY story rendered the same way (image shown if available).
    def _card(it):
        img = it.get("image_url")
        hero = (
            f'<tr><td style="padding:0 0 12px;"><img src="{_esc(img)}" width="536" '
            f'style="display:block;width:100%;max-width:536px;height:auto;border-radius:12px;" alt=""></td></tr>'
        ) if img else ""
        return f"""
    <tr><td style="padding:0 0 8px;font:12px/1 Arial,sans-serif;color:{_MUTED};">{_meta_line(it)}</td></tr>
    {hero}
    <tr><td style="padding:0 0 8px;"><a href="{detail_url(it["url"])}" style="font:700 19px/1.32 Arial,sans-serif;color:{_INK};text-decoration:none;letter-spacing:-.01em;">{_esc(it["title"])}</a></td></tr>
    <tr><td style="padding:0 0 10px;font:300 14.5px/1.6 Arial,sans-serif;color:{_MUTED};">{_esc(_clip(it["summary"]))}</td></tr>
    <tr><td style="font:12px/1 Arial,sans-serif;">{_email_players(it.get("players"))}<a href="{detail_url(it["url"])}" style="color:{_GOLD};font-weight:700;text-decoration:none;float:right;">Read →</a></td></tr>
    <tr><td style="padding:20px 0;"><div style="height:1px;background:#ece8dc;"></div></td></tr>"""

    cards = "".join(_card(it) for it in items)

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
      {week} &nbsp;|&nbsp; <a href="{home}/ai-news/" style="color:{_GOLD};text-decoration:none;">Read online →</a>
    </td></tr>
    <tr><td style="background:#0d0d0d;border-radius:16px;padding:30px 24px;text-align:center;">
      <div style="font:800 30px/1 Arial,sans-serif;color:#ECEAE3;letter-spacing:-.02em;">AI <span style="color:#e2ba6b;">News</span></div>
      <div style="font:700 11px/1 Arial,sans-serif;color:#9a938a;letter-spacing:.22em;text-transform:uppercase;margin-top:10px;">Weekly digest · {len(items)} stories</div>
    </td></tr>
    <tr><td style="padding:24px 0 4px;font:700 22px/1.25 Arial,sans-serif;color:{_INK};letter-spacing:-.01em;">This week in AI 🗞️</td></tr>
    <tr><td style="padding:0 0 18px;font:300 15px/1.6 Arial,sans-serif;color:{_MUTED};">{len(items)} stories — filtered, deduplicated and summarized.</td></tr>
    <tr><td style="padding:0 0 22px;"><div style="height:2px;background:{_GOLD};width:48px;"></div></td></tr>
    {cards}{empty}
    <tr><td style="padding:28px 0 0;text-align:center;">
      <a href="{home}/ai-news/" style="background:#0d0d0d;color:#e2ba6b;font:700 13px/1 Arial,sans-serif;text-decoration:none;padding:12px 24px;border-radius:999px;display:inline-block;">See all on the web →</a>
    </td></tr>
    {tg_cta}
    <tr><td style="padding:22px 0 0;text-align:center;font:12px/1.6 Arial,sans-serif;color:{_SOFT};">
      Curated &amp; deduplicated with AI · the score (0–100) is editorial relevance<br>
      <a href="{home}/" style="color:{_GOLD};text-decoration:none;">Manuel Mesonero</a> · AI News{addr}<br>
      Weekly · every Sunday · <a href="{unsub}" style="color:{_SOFT};text-decoration:underline;">Unsubscribe</a>
    </td></tr>
    </table>
   </td></tr>
  </table>
</td></tr></table></body></html>"""


_MIN_STORIES = 10  # curated default: the week's top 10...


async def _gather() -> list[dict]:
    # Last 7 days, relevant only (exclude 'baja'), ordered by boosted score.
    # Curated: the top _MIN_STORIES, PLUS any extra high-importance ('alta') story
    # beyond that so a busy week isn't cut short. Capped at email_max_items.
    items = await _collect(hours=168, limit=80)
    items = [it for it in items if (it.get("tier") or "medium") != "low"]
    extra_alta = [it for it in items[_MIN_STORIES:] if it.get("tier") == "high"]
    return (items[:_MIN_STORIES] + extra_alta)[: settings.email_max_items]


async def _send_via_brevo(items: list[dict], subject: str) -> int:
    """Public newsletter: create + send a Brevo campaign to the contact list.
    Brevo stores subscribers securely, injects a compliant 1-click unsubscribe, and
    handles bounces. Sender must be a verified sender in Brevo. Raises on API error
    so a failed send turns the Actions run RED."""
    import httpx

    sender_email = settings.email_from or settings.email_user
    week = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    html = _render_email(items, unsub_href="{{ unsubscribe }}")
    headers = {"api-key": settings.brevo_api_key, "content-type": "application/json"}
    async with httpx.AsyncClient(timeout=40) as client:
        # 1) create the campaign (draft)
        r = await client.post(
            "https://api.brevo.com/v3/emailCampaigns",
            headers=headers,
            json={
                "name": f"AI News Weekly · {week}",
                "subject": subject,
                "sender": {"name": "AI News", "email": sender_email},
                "htmlContent": html,
                "recipients": {"listIds": [settings.brevo_list_id]},
            },
        )
        if r.status_code >= 300:
            log.error("email.brevo_create_failed", status=r.status_code, body=r.text[:300])
            r.raise_for_status()
        campaign_id = r.json()["id"]
        # 2) send it now
        r2 = await client.post(
            f"https://api.brevo.com/v3/emailCampaigns/{campaign_id}/sendNow", headers=headers
        )
        if r2.status_code >= 300:
            log.error("email.brevo_send_failed", status=r2.status_code, body=r2.text[:300])
            r2.raise_for_status()
    log.info("email.sent", transport="brevo", campaign=campaign_id, list_id=settings.brevo_list_id, stories=len(items))
    return len(items)


def _send_via_smtp(items: list[dict], subject: str) -> int:
    """Private send to a fixed recipient list (EMAIL_TO) over SMTP — for you / a few
    people you add by hand. Raises on SMTP error so a broken send turns the run RED."""
    recipients = [r.strip() for r in settings.email_to.split(",") if r.strip()]
    sender = settings.email_from or settings.email_user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    # Standard one-click/list unsubscribe (mailto) — improves deliverability.
    msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=Unsubscribe>"
    msg.attach(MIMEText("Open this email in an HTML-capable client.", "plain"))
    msg.attach(MIMEText(_render_email(items), "html"))

    try:
        with smtplib.SMTP(settings.email_host, settings.email_port, timeout=30) as s:
            s.starttls()
            s.login(settings.email_user, settings.email_password)
            s.sendmail(msg["From"], recipients, msg.as_string())
        log.info("email.sent", transport="smtp", recipients=len(recipients), stories=len(items))
        return len(items)
    except Exception as e:
        log.error("email.failed", err=str(e)[:200])
        raise


async def send_weekly_digest() -> int:
    # Transport: Brevo (public list) if configured, else SMTP (private fixed list).
    use_brevo = bool(settings.brevo_api_key and settings.brevo_list_id)
    use_smtp = bool(settings.email_host and settings.email_user and settings.email_to)
    if not (use_brevo or use_smtp):
        log.info("email.not_configured")
        return 0

    items = await _gather()
    if not items:
        log.info("email.no_stories")
        return 0

    subject = f"🗞️ AI News · {len(items)} stories this week"
    if use_brevo:
        return await _send_via_brevo(items, subject)
    return _send_via_smtp(items, subject)


def main() -> None:
    configure_logging()
    asyncio.run(send_weekly_digest())


if __name__ == "__main__":
    main()
