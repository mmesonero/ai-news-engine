from __future__ import annotations

import pytest

from app.ingestion import HtmlIngestor, RssIngestor, YoutubeIngestor, get_ingestor


def test_get_ingestor_dispatches_by_type() -> None:
    assert isinstance(get_ingestor("rss"), RssIngestor)
    assert isinstance(get_ingestor("html"), HtmlIngestor)
    assert isinstance(get_ingestor("youtube"), YoutubeIngestor)


def test_get_ingestor_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_ingestor("twitter")
