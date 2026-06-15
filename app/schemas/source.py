from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["rss", "html", "youtube"]


class SourceCreate(BaseModel):
    name: str
    type: SourceType
    url: str
    active: bool = True
    config_json: dict[str, Any] = Field(default_factory=dict)
    group_name: str | None = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: SourceType
    url: str
    active: bool
    group_name: str | None = None
    created_at: datetime
