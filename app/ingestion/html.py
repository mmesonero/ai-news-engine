from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from app.logging_config import get_logger
from app.models.source import Source
from app.schemas.news import RawContentDraft
from app.url_safety import safe_get

log = get_logger(__name__)


class HtmlIngestor:
    """Minimal index-page scraper for sources without an RSS feed.

    Reads `config_json`:
      {
        "link_selector": "a.article-card",         # CSS selector for article links
        "title_selector": "h1",                    # CSS selector inside the article page
        "body_selector": "article",                # CSS selector for article body
        "max_articles": 10
      }
    Designed as a clean extension point — Playwright can be wired in later
    behind the same interface without changing callers.
    """

    async def fetch(self, source: Source) -> list[RawContentDraft]:
        cfg = source.config_json or {}
        link_sel = cfg.get("link_selector")
        body_sel = cfg.get("body_selector", "article")
        title_sel = cfg.get("title_selector", "h1")
        max_articles = int(cfg.get("max_articles", 10))
        if not link_sel:
            log.warning("html.missing_selectors", source=source.name)
            return []

        async with httpx.AsyncClient(timeout=20) as client:
            # safe_get validates the URL + each redirect hop is a public host (SSRF guard).
            index = await safe_get(client, source.url)
            index.raise_for_status()
            soup = BeautifulSoup(index.text, "lxml")
            links = []
            for a in soup.select(link_sel)[:max_articles]:
                href = a.get("href")
                if not href:
                    continue
                if href.startswith("/"):
                    href = httpx.URL(source.url).join(href).human_repr()
                links.append(href)

            drafts: list[RawContentDraft] = []
            for href in links:
                try:
                    page = await safe_get(client, href)
                    page.raise_for_status()
                    page_soup = BeautifulSoup(page.text, "lxml")
                    title_node = page_soup.select_one(title_sel)
                    body_node = page_soup.select_one(body_sel)
                    if not title_node or not body_node:
                        continue
                    drafts.append(
                        RawContentDraft(
                            external_id=href,
                            title=title_node.get_text(strip=True),
                            url=href,
                            author=None,
                            raw_text=body_node.get_text(separator="\n", strip=True),
                            published_at=None,
                            language="en",
                            metadata={},
                        )
                    )
                except Exception as e:  # pragma: no cover
                    log.warning("html.article_failed", url=href, err=str(e))
            return drafts
