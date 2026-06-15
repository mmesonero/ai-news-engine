from app.ingestion.base import Ingestor
from app.ingestion.html import HtmlIngestor
from app.ingestion.rss import RssIngestor
from app.ingestion.youtube import YoutubeIngestor


def get_ingestor(source_type: str) -> Ingestor:
    if source_type == "rss":
        return RssIngestor()
    if source_type == "html":
        return HtmlIngestor()
    if source_type == "youtube":
        return YoutubeIngestor()
    raise ValueError(f"Unknown source type: {source_type}")


__all__ = ["Ingestor", "RssIngestor", "HtmlIngestor", "YoutubeIngestor", "get_ingestor"]
