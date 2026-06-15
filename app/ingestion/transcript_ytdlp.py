"""yt-dlp-based transcript fallbacks.

Two strategies, tried in order:
  1) `fetch_transcript_via_ytdlp` — download YouTube subtitle track via yt-dlp.
     Free, fast. Fails when YouTube rate-limits the IP or the video has no
     captions.
  2) `fetch_transcript_via_whisper` — download audio via yt-dlp using the
     `android` player_client (different YouTube CDN/auth flow, survives many
     rate-limit scenarios), then transcribe with OpenAI Whisper. Paid but
     autonomous — no cookies, no proxy needed.

Optional config (env vars):
  - YT_DLP_PROXY            → passes `--proxy` to yt-dlp
  - YT_DLP_COOKIES_FILE     → passes `--cookies`
  - YT_DLP_PLAYER_CLIENTS   → comma-separated player_clients (default "android,tv_embedded")
"""
from __future__ import annotations

import asyncio
import glob
import os
import re
import subprocess
import tempfile

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

_VTT_TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> .*$")
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def _strip_vtt(content: str) -> str:
    """Turn a WebVTT/SRT subtitle file into plain text."""
    out_lines: list[str] = []
    seen: set[str] = set()
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "WEBVTT" or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if _VTT_TS_RE.match(line) or line.startswith("NOTE"):
            continue
        if line.isdigit():
            continue  # SRT counter
        line = _VTT_TAG_RE.sub("", line)
        if line in seen:  # auto-generated VTT often repeats every cue
            continue
        seen.add(line)
        out_lines.append(line)
    return " ".join(out_lines).strip()


def fetch_transcript_via_ytdlp(video_id: str, language: str = "en") -> str | None:
    """Download a video's subtitle track via yt-dlp and return plain text.

    Returns None on failure (missing subs, blocked, etc.)."""
    proxy = os.environ.get("YT_DLP_PROXY")
    cookies = os.environ.get("YT_DLP_COOKIES_FILE")

    with tempfile.TemporaryDirectory() as td:
        cmd = [
            "yt-dlp",
            f"https://www.youtube.com/watch?v={video_id}",
            "--skip-download",
            "--write-auto-sub",   # auto-generated captions (most videos have these)
            "--write-sub",        # human-uploaded if available
            "--sub-lang", f"{language}.*,{language}",
            "--sub-format", "vtt/srv1/best",
            "-o", os.path.join(td, "%(id)s"),
            "--quiet", "--no-warnings",
            "--no-cache-dir",
            "--retries", "2",
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])
        if cookies:
            cmd.extend(["--cookies", cookies])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            log.warning("ytdlp.timeout", video=video_id)
            return None

        if result.returncode != 0:
            err = (result.stderr or "")[:200]
            # Don't log 429/blocked at warning — pipeline will log it once at source-level.
            log.info("ytdlp.failed", video=video_id, err=err)
            return None

        # Look for any subtitle file the language pattern matched.
        for ext in ("vtt", "srv1", "srt"):
            files = sorted(glob.glob(os.path.join(td, f"*.{ext}")))
            if not files:
                continue
            try:
                with open(files[0], "r", encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                continue
            text = _strip_vtt(raw)
            if text:
                return text
        return None


# Local Whisper fallback: download audio via yt-dlp (android client bypasses
# many rate limits) + transcribe with faster-whisper running on CPU. Free,
# autonomous, portable. Disable via `enable_local_whisper=False` in cloud envs
# without spare CPU minutes (e.g. GitHub Actions free tier).

_AUDIO_MAX_BYTES = 200 * 1024 * 1024  # 200 MB sanity cap
_FASTER_WHISPER_MODEL: object | None = None  # lazily loaded singleton


def _get_whisper_model():
    """Lazy-load the faster-whisper model. Re-used across calls in the same process."""
    global _FASTER_WHISPER_MODEL
    if _FASTER_WHISPER_MODEL is None:
        from faster_whisper import WhisperModel
        model_name = settings.whisper_model
        log.info("whisper.loading_model", model=model_name)
        _FASTER_WHISPER_MODEL = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",  # 8-bit quant — fast on CPU, low RAM
        )
        log.info("whisper.model_loaded", model=model_name)
    return _FASTER_WHISPER_MODEL


def fetch_transcript_via_whisper(video_id: str, language: str = "en") -> str | None:
    """Download audio + transcribe locally via faster-whisper.
    Returns None when disabled, on download failure, or on transcription failure.
    No external API calls — fully autonomous and free (CPU time only)."""
    if not settings.enable_local_whisper:
        log.info("whisper.disabled", video=video_id)
        return None

    proxy = os.environ.get("YT_DLP_PROXY")
    cookies = os.environ.get("YT_DLP_COOKIES_FILE")
    clients = os.environ.get("YT_DLP_PLAYER_CLIENTS", "android,tv_embedded")

    with tempfile.TemporaryDirectory() as td:
        out_template = os.path.join(td, "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp",
            f"https://www.youtube.com/watch?v={video_id}",
            "-f", "worstaudio/worst",
            "-o", out_template,
            "--quiet", "--no-warnings", "--no-cache-dir",
            "--retries", "2",
            "--extractor-args", f"youtube:player_client={clients}",
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])
        if cookies:
            cmd.extend(["--cookies", cookies])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            log.warning("whisper.download_timeout", video=video_id)
            return None
        if result.returncode != 0:
            log.info("whisper.download_failed", video=video_id, err=(result.stderr or "")[:200])
            return None

        files = sorted(glob.glob(os.path.join(td, "*")))
        if not files:
            return None
        audio_path = files[0]
        size = os.path.getsize(audio_path)
        if size > _AUDIO_MAX_BYTES:
            log.warning("whisper.audio_too_large", video=video_id, bytes=size)
            return None

        try:
            model = _get_whisper_model()
            # `language` hint speeds inference. beam_size=1 = fastest, decent quality.
            segments, _info = model.transcribe(
                audio_path,
                language=language if language else None,
                beam_size=1,
                vad_filter=True,  # voice-activity detection — skip silences, speeds up
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text or None
        except Exception as e:
            log.warning("whisper.transcribe_failed", video=video_id, err=str(e)[:200])
            return None
