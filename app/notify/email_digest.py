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
from app.export.static_site import _THEME_EN, _collect, _esc, _site_home
from app.links import detail_url
from app.logging_config import configure_logging, get_logger

log = get_logger(__name__)


def _render_email(items: list[dict]) -> str:
    """Email-safe HTML (inline styles, light background): warm/gold to match the brand."""
    home = _site_home()
    rows = []
    for it in items:
        emoji, label = _THEME_EN.get(it["theme"], ("🌐", "Other"))
        score = it["relevance"] or it["score"] or 0
        title = _esc(it["title"] or "(untitled)")
        summary = _esc((it["summary"] or "")[:280])
        url = detail_url(it["url"])
        srcs = f' · 📡 {it["sources"]} sources' if it["sources"] > 1 else ""
        rows.append(
            f'<tr><td style="padding:18px 0;border-bottom:1px solid #e8e4d8;">'
            f'<div style="font:600 12px/1 Arial,sans-serif;color:#9a938a;letter-spacing:.04em;text-transform:uppercase;margin-bottom:6px;">'
            f'{emoji} {label} &nbsp;·&nbsp; {score}/100{srcs}</div>'
            f'<a href="{url}" style="font:600 18px/1.35 Arial,sans-serif;color:#1a1815;text-decoration:none;">{title}</a>'
            f'<p style="font:300 14px/1.6 Arial,sans-serif;color:#6b655c;margin:8px 0 0;">{summary}</p>'
            f'<a href="{url}" style="font:600 13px/1 Arial,sans-serif;color:#b0904c;text-decoration:none;display:inline-block;margin-top:8px;">Read on the web →</a>'
            f"</td></tr>"
        )
    week = datetime.now(timezone.utc).strftime("%d %b %Y")
    body = "".join(rows) or '<tr><td style="padding:24px 0;color:#6b655c;font:14px Arial;">No news this week.</td></tr>'
    return f"""<!DOCTYPE html><html><body style="margin:0;background:#fafaf7;padding:0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fafaf7;">
<tr><td align="center" style="padding:28px 16px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
    <tr><td style="padding:0 0 8px;">
      <div style="font:700 26px/1 Arial,sans-serif;color:#1a1815;letter-spacing:-.02em;">AI <span style="color:#b0904c;">News</span></div>
      <div style="font:14px Arial,sans-serif;color:#6b655c;margin-top:6px;">Weekly digest · {len(items)} stories · {week}</div>
    </td></tr>
    <tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{body}</table></td></tr>
    <tr><td style="padding:22px 0 0;font:12px Arial,sans-serif;color:#9a938a;">
      <a href="{home}/ai-news/" style="color:#b0904c;text-decoration:none;">See all on the web →</a> · auto-curated &amp; deduplicated
    </td></tr>
  </table>
</td></tr></table></body></html>"""


async def _gather() -> list[dict]:
    return await _collect(hours=168, limit=settings.email_max_items)  # last 7 days


async def send_weekly_digest() -> int:
    if not (settings.email_host and settings.email_user and settings.email_to):
        log.info("email.not_configured")
        return 0
    items = await _gather()
    if not items:
        log.info("email.no_stories")
        return 0

    recipients = [r.strip() for r in settings.email_to.split(",") if r.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"AI News — weekly digest ({len(items)} stories)"
    msg["From"] = settings.email_from or settings.email_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText("Open in an HTML-capable client.", "plain"))
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
