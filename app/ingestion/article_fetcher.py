"""Tiny readability-style article body extractor.

Used when an RSS feed only gives a short summary and we want full text for
embeddings / classification / enrichment. Deliberately heuristic — not a
full readability port. For sites we can't extract from reliably, the
ingestor falls back to the RSS body.
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.logging_config import get_logger
from app.url_safety import safe_get

log = get_logger(__name__)

# Ordered by specificity: try the most explicit signals first.
_BODY_SELECTORS: tuple[str, ...] = (
    "article [itemprop='articleBody']",
    "[itemprop='articleBody']",
    "article .article-content",
    "article .entry-content",
    "article .post-content",
    "article",
    "main article",
    "div.article-content",
    "div.entry-content",
    "div.post-content",
    "main",
)

_NOISE_SELECTORS: tuple[str, ...] = (
    "script", "style", "nav", "footer", "header", "aside",
    "form", "iframe", "noscript",
    "[class*='related']", "[class*='newsletter']", "[class*='subscribe']",
    "[class*='advertisement']", "[id*='comments']",
)


def _clean(node: Tag) -> str:
    for sel in _NOISE_SELECTORS:
        for n in node.select(sel):
            n.decompose()
    text = node.get_text(separator="\n", strip=True)
    # Collapse triple+ newlines.
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


async def fetch_article_body(url: str, *, max_chars: int = 12000, timeout: float = 15.0) -> str | None:
    """Fetch the URL and return the best-guess article body, or None if extraction failed."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; AINewsEngine/0.1; "
                    "+https://github.com/your-org/ai-news-engine)"
                )
            },
        ) as client:
            # safe_get validates the URL + every redirect hop is a public host (SSRF guard).
            resp = await safe_get(client, url)
            resp.raise_for_status()
    except Exception as e:
        log.warning("augment.fetch_failed", url=url, err=str(e))
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    for sel in _BODY_SELECTORS:
        node = soup.select_one(sel)
        if node is None:
            continue
        text = _clean(node)
        if len(text) >= 400:
            return text[:max_chars]
    return None
