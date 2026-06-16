"""Find a representative image for an article (og:image / twitter:image), or the
YouTube thumbnail for video URLs. Used to show a hero image on the web detail
page and a photo in Telegram. Best-effort — failures just leave image_url NULL.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models.cluster import ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent

log = get_logger(__name__)

_UA = "Mozilla/5.0 (compatible; ai-news-bot/1.0)"
_OG = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|og:image:url|twitter:image)["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)["\']',
    re.IGNORECASE,
)


def _youtube_thumb(url: str) -> str | None:
    try:
        u = urlparse(url)
        host = u.netloc.lower()
        vid = None
        if "youtu.be" in host:
            vid = u.path.lstrip("/").split("/")[0]
        elif "youtube.com" in host:
            if u.path.startswith("/watch"):
                vid = parse_qs(u.query).get("v", [None])[0]
            elif u.path.startswith(("/embed/", "/shorts/")):
                vid = u.path.split("/")[2]
        if vid:
            return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    except Exception:
        pass
    return None


async def _image_for(client: httpx.AsyncClient, url: str) -> str | None:
    if not url:
        return None
    yt = _youtube_thumb(url)
    if yt:
        return yt
    try:
        r = await client.get(url, headers={"User-Agent": _UA}, follow_redirects=True, timeout=10)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            return None
        html = r.text[:200000]
        m = _OG.search(html) or _OG_REV.search(html)
        if m:
            return urljoin(str(r.url), m.group(1).strip())
    except Exception as e:
        log.info("image.fetch_failed", url=url[:80], err=str(e)[:120])
    return None


async def backfill_images(session: AsyncSession, limit: int = 40) -> int:
    """Fetch a hero image for representative stories that don't have one yet."""
    rows = await session.execute(
        select(RawContent)
        .join(ContentCluster, ContentCluster.representative_content_id == RawContent.id)
        .join(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
        .where(RawContent.image_url.is_(None))
        .where(ProcessedContent.is_noise.is_(False))
        .where(ProcessedContent.theme.isnot(None))
        .where(ProcessedContent.theme != "irrelevante")
        .limit(limit)
    )
    raws = list(rows.scalars())
    if not raws:
        return 0
    found = 0
    async with httpx.AsyncClient() as client:
        for raw in raws:
            img = await _image_for(client, raw.url)
            if img:
                raw.image_url = img
                found += 1
    if found:
        await session.commit()
    log.info("image.backfill", found=found, checked=len(raws))
    return found
