from __future__ import annotations

from app.ai.prompts import (
    CLASSIFY_NOISE_V1_USER,
    CLUSTER_TOPIC_V1_USER,
    ENRICH_V1_USER,
    LINKEDIN_V1_USER,
    SAME_EVENT_V1_USER,
    VIDEO_WORTH_V1_USER,
)
from app.ai.sanitize import BEGIN_MARK, END_MARK, wrap, wrap_article, wrap_fields


def test_classify_prompt_substitutes_all_placeholders() -> None:
    rendered = CLASSIFY_NOISE_V1_USER.format(
        article=wrap_article(title="OpenAI ships X", url="https://example.com/x", body="...")
    )
    assert "OpenAI ships X" in rendered
    assert "https://example.com/x" in rendered
    assert "{article}" not in rendered


def test_enrich_prompt_substitutes_all_placeholders() -> None:
    rendered = ENRICH_V1_USER.format(article=wrap_article(title="t", url="u", body="b"))
    assert "{article}" not in rendered


def test_linkedin_prompt_substitutes_all_placeholders() -> None:
    rendered = LINKEDIN_V1_USER.format(article=wrap_fields(TITLE="t", SUMMARY="s", INSIGHTS="{}"))
    assert "{article}" not in rendered


def test_cluster_topic_prompt_substitutes_all_placeholders() -> None:
    rendered = CLUSTER_TOPIC_V1_USER.format(titles=wrap("- a\n- b"))
    assert "{titles}" not in rendered
    assert "- a" in rendered


def test_same_event_prompt_substitutes_all_placeholders() -> None:
    rendered = SAME_EVENT_V1_USER.format(items=wrap_fields(ITEM_A_TITLE="a", ITEM_B_TITLE="b"))
    assert "{items}" not in rendered


def test_video_worth_prompt_substitutes_all_placeholders() -> None:
    rendered = VIDEO_WORTH_V1_USER.format(video=wrap_fields(TITLE="t", CHANNEL="c"))
    assert "{video}" not in rendered


# --------------------------------------------------------------------- #
# Fencing: no attacker-influenceable value may sit outside the markers.
# A feed title is exactly as untrusted as the article body — fencing only the
# body left title/url in instruction space, where INJECTION_GUARD (which scopes
# itself to "text between the markers") did not cover them.
# --------------------------------------------------------------------- #
def _is_fenced(rendered: str, payload: str) -> bool:
    """True when every occurrence of `payload` sits inside a BEGIN/END region."""
    assert payload in rendered, "payload missing — test would pass vacuously"
    segments = rendered.split(BEGIN_MARK)
    if payload in segments[0]:  # before any fence
        return False
    for region in segments[1:]:
        parts = region.split(END_MARK, 1)
        if len(parts) == 2 and payload in parts[1]:  # after a fence closed
            return False
    return True


def test_classify_fences_title_and_url_not_just_body() -> None:
    rendered = CLASSIFY_NOISE_V1_USER.format(
        article=wrap_article(title="EVILTITLE", url="http://evil/URLMARK", body="BODYMARK")
    )
    for payload in ("EVILTITLE", "URLMARK", "BODYMARK"):
        assert _is_fenced(rendered, payload)


def test_enrich_fences_title_and_url() -> None:
    rendered = ENRICH_V1_USER.format(
        article=wrap_article(title="EVILTITLE", url="http://evil/URLMARK", body="b")
    )
    for payload in ("EVILTITLE", "URLMARK"):
        assert _is_fenced(rendered, payload)


def test_video_worth_fences_title_and_channel() -> None:
    rendered = VIDEO_WORTH_V1_USER.format(
        video=wrap_fields(TITLE="EVILTITLE", CHANNEL="EVILCHANNEL")
    )
    for payload in ("EVILTITLE", "EVILCHANNEL"):
        assert _is_fenced(rendered, payload)


def test_same_event_fences_titles_and_summaries() -> None:
    rendered = SAME_EVENT_V1_USER.format(
        items=wrap_fields(
            ITEM_A_TITLE="EVILA",
            ITEM_A_SUMMARY="SUMA",
            ITEM_B_TITLE="EVILB",
            ITEM_B_SUMMARY="SUMB",
        )
    )
    for payload in ("EVILA", "SUMA", "EVILB", "SUMB"):
        assert _is_fenced(rendered, payload)
