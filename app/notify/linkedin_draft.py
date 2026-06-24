"""LinkedIn post DRAFTS delivered to Telegram for manual approve + paste.

No LinkedIn API: the engine writes the post text, sends it to your Telegram as a
copy-ready block, and YOU paste it into LinkedIn (human-in-the-loop). Two kinds:

  - weekly:   Sunday "This week in AI" — the SAME stories as the email digest.
  - breaking: one big story (boosted >= LINKEDIN_MIN_SCORE), at most one per run;
              each story is drafted only once (linkedin_drafted_at gate).

Drafts go to LINKEDIN_DRAFT_CHAT_ID (your DM with the bot) if set, else the normal
telegram chat — set it so drafts never land on the public channel.
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.links import detail_url
from app.logging_config import configure_logging, get_logger
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.notify.email_digest import _gather

log = get_logger(__name__)

_HASHTAGS = "#AI #ArtificialIntelligence #MachineLearning #TechNews"
_MAX_WEEKLY = 5  # stories featured in the weekly post (title + short paragraph each)


def _web() -> str:
    return settings.public_site_base.rstrip("/") + "/"


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _hashtag(name: str) -> str:
    h = re.sub(r"[^A-Za-z0-9]", "", name or "")
    return f"#{h}" if h else ""


def _clip(s: str, n: int = 320) -> str:
    """Trim without cutting mid-sentence (last sentence end, else last word + …)."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= int(n * 0.5):
        return cut[: end + 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut).rstrip(" ,;:") + "…"


# ---------- pure formatters (no DB / no network — easy to preview & test) ----------

def weekly_body(items: list[dict]) -> tuple[str, str]:
    """Return (post_body, first_comment) for the weekly digest — the top stories,
    each as a headline followed by a short paragraph (no bullets)."""
    blocks = []
    for it in items[:_MAX_WEEKLY]:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        summ = _clip(it.get("summary") or "", 240)
        blocks.append(f"{title}\n{summ}" if summ else title)
    body = (
        "🗞️ This week in AI\n\n"
        "The stories that mattered — deduplicated and ranked:\n\n"
        + "\n\n".join(blocks)
        + "\n\n📲 Get this briefing every week — on Telegram or by email. Link in comments 👇\n\n"
        + _HASHTAGS
    )
    first_comment = f"Full briefing + free signup (Telegram or email): {_web()}"
    return body, first_comment


def breaking_body(title: str, summary: str, players: list[str], url: str) -> tuple[str, str]:
    """Return (post_body, first_comment) for a single breaking story."""
    players = [p for p in (players or []) if p][:3]
    tags = "#AI #ArtificialIntelligence " + " ".join(_hashtag(p) for p in players)
    parts = [f"🚨 {title.strip()}", ""]
    summ = _clip(summary)
    if summ:
        parts += [summ, ""]
    if players:
        parts += ["Players: " + ", ".join(players), ""]
    parts += [
        "📲 Daily AI news, deduplicated — on Telegram or by email. Link in comments 👇",
        "",
        tags.strip(),
    ]
    body = "\n".join(parts)
    first_comment = f"Read more + free signup: {detail_url(url)}"
    return body, first_comment


# ---------- delivery ----------

async def _send_to_telegram(label: str, body: str, first_comment: str) -> bool:
    chat = settings.linkedin_draft_chat_id or settings.telegram_chat_id
    if not settings.telegram_bot_token or not chat:
        log.info("linkedin.not_configured")
        return False
    # <pre> blocks get a one-tap "copy" affordance in Telegram clients.
    text = (
        f"📝 <b>{_esc(label)}</b> — copy &amp; paste to LinkedIn\n\n"
        f"<pre>{_esc(body)}</pre>\n"
        f"💬 <b>First comment:</b>\n<pre>{_esc(first_comment)}</pre>"
    )
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        )
        ok = bool(r.json().get("ok"))
        if not ok:
            log.warning("linkedin.telegram_failed", body=r.text[:200])
        return ok


# ---------- builders ----------

async def build_and_send_weekly() -> int:
    """Weekly LinkedIn draft from the SAME stories as the email digest."""
    items = await _gather()
    if not items:
        log.info("linkedin.weekly_no_stories")
        return 0
    body, first_comment = weekly_body(items)
    ok = await _send_to_telegram("LinkedIn draft · Weekly", body, first_comment)
    log.info("linkedin.weekly", sent=int(ok), stories=len(items))
    return 1 if ok else 0


async def build_and_send_breaking(session: AsyncSession) -> int:
    """Draft EVERY fresh story above the threshold (boosted >= LINKEDIN_MIN_SCORE),
    each one only once. No per-day cap — the linkedin_drafted_at gate stops repeats.
    A generous safety cap avoids flooding if scoring ever goes haywire."""
    if not settings.telegram_bot_token:
        log.info("linkedin.not_configured")
        return 0
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=48)
    sources = func.count(func.distinct(RawContent.source_id))
    boosted = func.coalesce(ProcessedContent.importance_score, 0) + func.least(20, (sources - 1) * 8)
    stmt = (
        select(ContentCluster, RawContent, ProcessedContent)
        .join(RawContent, RawContent.id == ContentCluster.representative_content_id)
        .join(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .join(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
        .where(ContentCluster.linkedin_drafted_at.is_(None))
        .where(ProcessedContent.is_noise.is_(False))
        .where(ProcessedContent.theme.isnot(None))
        .where(ProcessedContent.theme != "irrelevant")
        .where(
            or_(
                RawContent.published_at >= since,
                (RawContent.published_at.is_(None)) & (RawContent.fetched_at >= since),
            )
        )
        .group_by(ContentCluster.id, RawContent.id, ProcessedContent.id)
        .having(boosted >= settings.linkedin_min_score)
        .order_by(desc(boosted))
        .limit(10)  # safety backstop only; ≥ threshold is rare
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        log.info("linkedin.no_breaking")
        return 0
    sent = 0
    for cluster, raw, proc in rows:
        body, first_comment = breaking_body(
            title=proc.title_es or raw.title or "(untitled)",
            summary=proc.cleaned_summary or "",
            players=proc.players or [],
            url=raw.url,
        )
        if await _send_to_telegram("LinkedIn draft · Breaking", body, first_comment):
            cluster.linkedin_drafted_at = now  # never re-draft this story
            await session.commit()  # mark per-message so a mid-run failure never re-sends
            sent += 1
            await asyncio.sleep(0.5)  # stay under Telegram per-chat rate limit
    log.info("linkedin.breaking", sent=sent, candidates=len(rows))
    return sent


def main() -> None:
    configure_logging()
    kind = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    if kind == "breaking":
        async def _run() -> int:
            async with SessionLocal() as session:
                return await build_and_send_breaking(session)
        asyncio.run(_run())
    else:
        asyncio.run(build_and_send_weekly())


if __name__ == "__main__":
    main()
