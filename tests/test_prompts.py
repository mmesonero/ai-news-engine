from __future__ import annotations

from app.ai.prompts import (
    CLASSIFY_NOISE_V1_USER,
    CLUSTER_TOPIC_V1_USER,
    ENRICH_V1_USER,
    LINKEDIN_V1_USER,
)


def test_classify_prompt_substitutes_all_placeholders() -> None:
    rendered = CLASSIFY_NOISE_V1_USER.format(
        title="OpenAI ships X", url="https://example.com/x", body="..."
    )
    assert "OpenAI ships X" in rendered
    assert "https://example.com/x" in rendered
    assert "{title}" not in rendered


def test_enrich_prompt_substitutes_all_placeholders() -> None:
    rendered = ENRICH_V1_USER.format(title="t", url="u", body="b")
    for token in ("{title}", "{url}", "{body}"):
        assert token not in rendered


def test_linkedin_prompt_substitutes_all_placeholders() -> None:
    rendered = LINKEDIN_V1_USER.format(title="t", summary="s", insights="{}")
    for token in ("{title}", "{summary}", "{insights}"):
        assert token not in rendered


def test_cluster_topic_prompt_substitutes_all_placeholders() -> None:
    rendered = CLUSTER_TOPIC_V1_USER.format(titles="- a\n- b")
    assert "{titles}" not in rendered
    assert "- a" in rendered
