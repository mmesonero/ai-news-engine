from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.linkedin import LinkedinAngles, LinkedinIdea
from app.schemas.news import NewsItem, ProcessedRead, RawContentDraft
from app.schemas.source import SourceCreate


def test_source_create_defaults() -> None:
    s = SourceCreate(name="X", type="rss", url="https://x/feed")
    assert s.active is True
    assert s.config_json == {}


def test_raw_content_draft_optional_fields() -> None:
    d = RawContentDraft(
        external_id=None,
        title="t",
        url="https://x/y",
        raw_text="body",
    )
    assert d.author is None
    assert d.language == "en"
    assert d.metadata == {}


def test_linkedin_angles_empty_defaults() -> None:
    a = LinkedinAngles()
    assert a.hooks == []
    assert a.future_predictions == []


def test_linkedin_idea_round_trip() -> None:
    news = NewsItem(
        id=1, source_id=1, title="t", url="u", author=None, published_at=datetime.now(timezone.utc)
    )
    idea = LinkedinIdea(
        content_id=1,
        cluster_id=None,
        linkedin_potential_score=80,
        angles=LinkedinAngles(hooks=["h1"]),
        source=news,
    )
    dumped = idea.model_dump()
    assert dumped["angles"]["hooks"] == ["h1"]


def test_processed_read_validates_minimum() -> None:
    p = ProcessedRead(
        cleaned_summary=None,
        key_topics=[],
        novelty_score=None,
        importance_score=None,
        linkedin_potential_score=None,
        business_impact_score=None,
        ai_generated_insights={},
        linkedin_angles={},
        is_noise=False,
    )
    assert p.is_noise is False
