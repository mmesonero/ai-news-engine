from __future__ import annotations

from typing import Protocol

from app.models.source import Source
from app.schemas.news import RawContentDraft


class Ingestor(Protocol):
    async def fetch(self, source: Source) -> list[RawContentDraft]:
        ...
