from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import mktime

import feedparser
from bs4 import BeautifulSoup

from app.ingestion.article_fetcher import fetch_article_body
from app.logging_config import get_logger
from app.models.source import Source
from app.schemas.news import RawContentDraft

log = get_logger(__name__)


class RssIngestor:
    """Parses an RSS/Atom feed.

    `source.config_json` flags:
      - `fetch_full_text` (bool, default False) — if True, fetches the article URL
        whenever the RSS body is shorter than `min_chars`, and replaces the body
        with the extracted main text.
      - `min_chars` (int, default 800) — threshold under which the augment kicks in.
    """

    async def fetch(self, source: Source) -> list[RawContentDraft]:
        feed = await asyncio.to_thread(feedparser.parse, source.url)
        if feed.bozo and not feed.entries:
            log.warning("rss.parse_error", source=source.name, err=str(feed.bozo_exception))
            return []
        drafts: list[RawContentDraft] = []
        for entry in feed.entries:
            try:
                drafts.append(self._entry_to_draft(entry))
            except Exception as e:  # pragma: no cover - resilient per-entry
                log.warning("rss.entry_failed", source=source.name, err=str(e))

        cfg = source.config_json or {}
        if cfg.get("fetch_full_text"):
            await self._augment_short_bodies(drafts, min_chars=int(cfg.get("min_chars", 800)))
        return drafts

    @staticmethod
    async def _augment_short_bodies(drafts: list[RawContentDraft], *, min_chars: int) -> None:
        async def _augment(d: RawContentDraft) -> None:
            if len(d.raw_text) >= min_chars or not d.url:
                return
            full = await fetch_article_body(d.url)
            if full and len(full) > len(d.raw_text):
                d.raw_text = full
                d.metadata = {**d.metadata, "body_source": "url_fetch"}

        await asyncio.gather(*[_augment(d) for d in drafts])

    @staticmethod
    def _entry_to_draft(entry: dict) -> RawContentDraft:
        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
        external_id = entry.get("id") or entry.get("guid") or url
        author = entry.get("author")
        body_html = (
            entry.get("content", [{}])[0].get("value")
            if entry.get("content")
            else entry.get("summary") or entry.get("description") or ""
        )
        body = BeautifulSoup(body_html or "", "lxml").get_text(separator="\n").strip()
        published: datetime | None = None
        for key in ("published_parsed", "updated_parsed"):
            tup = entry.get(key)
            if tup:
                published = datetime.fromtimestamp(mktime(tup), tz=timezone.utc)
                break
        return RawContentDraft(
            external_id=external_id,
            title=title,
            url=url,
            author=author,
            raw_text=body,
            published_at=published,
            language="en",
            metadata={"rss_tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")]},
        )
