"""YouTube ingestor — no API key required.

Strategy:
1. Resolve @handle → UC channel id by scraping the channel HTML page.
   - One-time, cached into `source.config_json["resolved_channel_id"]`.
   - Uses an EU consent cookie so EU IPs don't get the consent wall.
2. Fetch the 15 most recent videos via the channel's public Atom feed:
       https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxx
   - No auth, no key, no quota.
3. Fetch transcript via `youtube-transcript-api` (also keyless).

`source.url` accepts:
  - a UC channel id (`UCV03SRZ...`)
  - an `@handle` (`@claude`, `@anthropic-ai`) — resolved on first run.

`source.config_json`:
  {
    "max_results": 5,
    "language_codes": ["en"],
    "resolved_channel_id": "UCxxxx..."   # auto-populated after first resolve
  }
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from time import mktime

import feedparser
import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
)

from app.config import settings
from app.ingestion.transcript_ytdlp import (
    fetch_transcript_via_whisper,
    fetch_transcript_via_ytdlp,
)
from app.ingestion.video_filter import cheap_pre_filter, gpt_worth_transcribing
from app.logging_config import get_logger
from app.models.source import Source
from app.schemas.news import RawContentDraft

log = get_logger(__name__)

# Bypass YouTube's EU consent interstitial — otherwise the channel page
# returns the consent wall instead of the real HTML.
_CONSENT_COOKIES = {"CONSENT": "YES+1", "SOCS": "CAI"}
_USER_AGENT = "Mozilla/5.0 (compatible; AINewsEngine/0.1)"

_UC_RE = re.compile(r'"externalId":"(UC[a-zA-Z0-9_-]{22})"')
_UC_CHANNEL_LINK_RE = re.compile(r'channel/(UC[a-zA-Z0-9_-]{22})')


class YoutubeIngestor:
    async def fetch(self, source: Source) -> list[RawContentDraft]:
        cfg = dict(source.config_json or {})
        max_results = int(cfg.get("max_results", 5))
        langs = cfg.get("language_codes", ["en"])

        channel_id = await self._ensure_channel_id(source, cfg)
        if channel_id is None:
            log.warning("youtube.unresolved_channel", source=source.name, url=source.url)
            return []

        videos = await asyncio.to_thread(self._list_recent_via_rss, channel_id, max_results)
        drafts: list[RawContentDraft] = []
        ip_blocked = False
        whisper_calls_remaining = settings.whisper_max_per_run
        for v in videos:
            video_url = f"https://www.youtube.com/watch?v={v['id']}"

            # --- PRE-TRANSCRIPT FILTERS (cheapest first) ---
            ok, reason = cheap_pre_filter(v["title"], video_url)
            if not ok:
                log.info(
                    "youtube.prefilter_drop",
                    source=source.name, video=v["id"], title=v["title"][:80], reason=reason,
                )
                continue
            worth, judge_reason = await gpt_worth_transcribing(v["title"], v.get("channel_title"))
            if not worth:
                log.info(
                    "youtube.judge_drop",
                    source=source.name, video=v["id"], title=v["title"][:80], reason=judge_reason,
                )
                continue
            # --- END pre-filters ---

            transcript: str | None = None
            # Primary: youtube-transcript-api (fast, no subprocess).
            try:
                transcript = await asyncio.to_thread(self._get_transcript, v["id"], langs)
            except (IpBlocked, RequestBlocked):
                ip_blocked = True
            except Exception as e:
                log.warning("youtube.transcript_failed", video=v["id"], err=str(e))
            lang = langs[0] if langs else "en"
            # Fallback 1: yt-dlp subtitle download (free, different CDN endpoint).
            if transcript is None:
                transcript = await asyncio.to_thread(fetch_transcript_via_ytdlp, v["id"], lang)
                if transcript:
                    log.info("youtube.transcript_via_ytdlp", video=v["id"])
                    ip_blocked = False
            # Fallback 2 (free, autonomous): yt-dlp audio (android client) +
            # local faster-whisper. Slow on CPU but bypasses YouTube blocks.
            # Capped per run to prevent CPU runaway.
            if transcript is None and whisper_calls_remaining > 0:
                transcript = await asyncio.to_thread(
                    fetch_transcript_via_whisper, v["id"], lang
                )
                whisper_calls_remaining -= 1
                if transcript:
                    log.info(
                        "youtube.transcript_via_whisper",
                        video=v["id"], remaining=whisper_calls_remaining,
                    )
                    ip_blocked = False
            elif transcript is None and whisper_calls_remaining == 0:
                log.info("youtube.whisper_cap_hit", video=v["id"])
            if not transcript:
                if ip_blocked:
                    log.warning(
                        "youtube.all_paths_failed",
                        source=source.name, video=v["id"],
                    )
                else:
                    log.info("youtube.no_transcript", video=v["id"], title=v["title"][:80])
                continue
            drafts.append(
                RawContentDraft(
                    external_id=v["id"],
                    title=v["title"],
                    url=f"https://www.youtube.com/watch?v={v['id']}",
                    author=v.get("channel_title"),
                    raw_text=transcript,
                    published_at=v.get("published_at"),
                    language=langs[0] if langs else "en",
                    metadata={"channel_id": channel_id},
                )
            )
        return drafts

    # ------------------------------------------------------------------ #
    # Handle / channel-id resolution                                     #
    # ------------------------------------------------------------------ #

    async def _ensure_channel_id(self, source: Source, cfg: dict) -> str | None:
        url = (source.url or "").strip()
        if url.startswith("UC") and len(url) >= 24:
            return url
        cached = cfg.get("resolved_channel_id")
        if cached:
            return str(cached)
        handle = url.lstrip("@")
        if not handle:
            return None
        resolved = await asyncio.to_thread(self._resolve_handle_via_html, handle)
        if resolved:
            cfg["resolved_channel_id"] = resolved
            source.config_json = cfg
            log.info("youtube.handle_resolved", handle=handle, channel_id=resolved)
        return resolved

    @staticmethod
    def _resolve_handle_via_html(handle: str) -> str | None:
        """Fetch the @handle page and scrape the canonical UC channel id."""
        url = f"https://www.youtube.com/@{handle}"
        try:
            r = httpx.get(
                url,
                follow_redirects=True,
                cookies=_CONSENT_COOKIES,
                headers={"User-Agent": _USER_AGENT},
                timeout=15.0,
            )
            r.raise_for_status()
        except Exception as e:
            log.warning("youtube.handle_fetch_failed", handle=handle, err=str(e))
            return None

        m = _UC_RE.search(r.text)
        if m:
            return m.group(1)
        m = _UC_CHANNEL_LINK_RE.search(r.text)
        if m:
            return m.group(1)
        return None

    # ------------------------------------------------------------------ #
    # Channel feed                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _list_recent_via_rss(channel_id: str, max_results: int) -> list[dict]:
        """Public per-channel Atom feed. Returns up to `max_results` recent uploads.
        YouTube Shorts are filtered out at this layer (URL contains /shorts/)."""
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        feed = feedparser.parse(feed_url)
        out: list[dict] = []
        for entry in feed.entries:
            link = entry.get("link", "")
            if "/shorts/" in link:
                continue  # skip Shorts entirely
            video_id = entry.get("yt_videoid") or entry.get("id", "").split(":")[-1]
            if not video_id:
                continue
            published: datetime | None = None
            tup = entry.get("published_parsed") or entry.get("updated_parsed")
            if tup:
                published = datetime.fromtimestamp(mktime(tup))
            out.append(
                {
                    "id": video_id,
                    "title": entry.get("title", "").strip(),
                    "channel_id": channel_id,
                    "channel_title": entry.get("author"),
                    "published_at": published,
                }
            )
            if len(out) >= max_results:
                break
        return out

    # ------------------------------------------------------------------ #
    # Transcript                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_transcript(video_id: str, languages: list[str]) -> str | None:
        """youtube-transcript-api v1.x: instance-based `fetch()`.
        Tries the requested languages, then falls back to any other available
        transcript (manual or auto-generated)."""
        api = YouTubeTranscriptApi()
        try:
            fetched = api.fetch(video_id, languages=languages)
        except NoTranscriptFound:
            try:
                listing = api.list(video_id)
            except (TranscriptsDisabled, VideoUnavailable, CouldNotRetrieveTranscript):
                return None
            transcript = next(iter(listing), None)
            if transcript is None:
                return None
            fetched = transcript.fetch()
        except (TranscriptsDisabled, VideoUnavailable, CouldNotRetrieveTranscript):
            return None

        text = " ".join(snip.text for snip in fetched.snippets).strip()
        return text or None
