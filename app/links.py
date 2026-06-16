"""Stable per-story links to the public site detail pages.

Shared by the static-site generator (which creates the pages) and the Telegram
notifier (which links to them) so both agree on the URL. The slug is a hash of
the representative URL → deterministic and known before the page is published.
"""
from __future__ import annotations

import hashlib

from app.config import settings


def story_slug(url: str | None) -> str:
    return hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:12]


def detail_path(url: str | None) -> str:
    """Relative path of the detail page, e.g. 'n/abc123def456.html'."""
    return f"n/{story_slug(url)}.html"


def detail_url(url: str | None) -> str:
    """Absolute URL of the detail page on the public site."""
    base = settings.public_site_base.rstrip("/")
    return f"{base}/{detail_path(url)}"
