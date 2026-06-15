"""Pre-transcript filters for YouTube videos.

Saves money + CPU by rejecting videos BEFORE we pay to transcribe them.

Layers (cheapest first):
  1. Shorts → drop (low signal, low duration, mostly promo)
  2. Promo / topic keyword filters (regex, free)
  3. GPT title judge — gpt-4o-mini, ~$0.000015 per call. Decides if the
     title suggests genuine industry-shifting news worth transcribing.
"""
from __future__ import annotations

from app.ai.openai_client import json_completion
from app.ai.prompts import INJECTION_GUARD, VIDEO_WORTH_V1_SYSTEM, VIDEO_WORTH_V1_USER
from app.ai.sanitize import neutralize
from app.ingestion.topic_filter import is_promo, matches_topic
from app.logging_config import get_logger

log = get_logger(__name__)


def is_short(url: str) -> bool:
    """YouTube Shorts have URLs like https://www.youtube.com/shorts/<id>."""
    return "/shorts/" in (url or "")


def cheap_pre_filter(title: str, url: str) -> tuple[bool, str | None]:
    """Free, instant pre-filter. Returns (ok_to_continue, reject_reason)."""
    if not title:
        return False, "empty_title"
    if is_short(url):
        return False, "short_video"
    if is_promo(title):
        return False, "promo_pattern"
    # For YouTube, we don't require topic_filter — the channel is already
    # curated as AI-focused. (If we were ingesting random YT, we would.)
    return True, None


async def gpt_worth_transcribing(title: str, channel: str | None) -> tuple[bool, str]:
    """LLM-judged go/no-go. Conservative — defaults to no when uncertain.
    Costs ~$0.000015 per call (gpt-4o-mini, ~150 tokens in/out).
    Returns (worth, reason)."""
    try:
        payload = await json_completion(
            system=INJECTION_GUARD + VIDEO_WORTH_V1_SYSTEM,
            user=VIDEO_WORTH_V1_USER.format(
                title=neutralize(title, 300), channel=neutralize(channel or "unknown", 120)
            ),
            temperature=0.0,
        )
    except Exception as e:
        log.warning("video_judge.failed", err=str(e)[:120])
        # On LLM failure, default to allow — don't lose content because of a transient API hiccup.
        return True, "judge_unavailable"
    worth = bool(payload.get("worth", False))
    reason = payload.get("reason") or ("worth" if worth else "rejected")
    return worth, str(reason)[:160]
