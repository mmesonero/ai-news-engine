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


# Audio-transcription fallback: download audio via yt-dlp (android client
# bypasses many rate limits), then transcribe. Two backends (settings.transcribe_backend):
#   "openai" → OpenAI transcription API. No CPU; portable; works on GitHub Actions.
#   "local"  → faster-whisper on CPU. Free but heavy; respects enable_local_whisper.

_AUDIO_MAX_BYTES = 200 * 1024 * 1024       # local backend sanity cap
_OPENAI_AUDIO_MAX_BYTES = 25 * 1024 * 1024  # OpenAI transcription hard limit (25 MB)
_FASTER_WHISPER_MODEL: object | None = None  # lazily loaded singleton
_OPENAI_SYNC_CLIENT: object | None = None


def _download_audio(video_id: str, dest_dir: str) -> str | None:
    """Download the smallest audio track for a video via yt-dlp. Returns the
    file path, or None on failure."""
    proxy = os.environ.get("YT_DLP_PROXY")
    cookies = os.environ.get("YT_DLP_COOKIES_FILE")
    clients = os.environ.get("YT_DLP_PLAYER_CLIENTS", "android,tv_embedded")

    out_template = os.path.join(dest_dir, "%(id)s.%(ext)s")
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
        log.warning("transcribe.download_timeout", video=video_id)
        return None
    if result.returncode != 0:
        log.info("transcribe.download_failed", video=video_id, err=(result.stderr or "")[:200])
        return None

    files = sorted(glob.glob(os.path.join(dest_dir, "*")))
    return files[0] if files else None


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


def _get_openai_sync_client():
    global _OPENAI_SYNC_CLIENT
    if _OPENAI_SYNC_CLIENT is None:
        from openai import OpenAI
        _OPENAI_SYNC_CLIENT = OpenAI(api_key=settings.openai_api_key)
    return _OPENAI_SYNC_CLIENT


def _transcribe_openai(audio_path: str, video_id: str) -> str | None:
    """Transcribe a downloaded audio file via the OpenAI transcription API."""
    size = os.path.getsize(audio_path)
    if size > _OPENAI_AUDIO_MAX_BYTES:
        log.warning("transcribe.openai_too_large", video=video_id, bytes=size)
        return None
    try:
        client = _get_openai_sync_client()
        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model=settings.openai_transcribe_model,
                file=f,
                response_format="text",
            )
        text = (resp if isinstance(resp, str) else getattr(resp, "text", "")) or ""
        text = text.strip()
        if text:
            log.info("transcribe.openai_ok", video=video_id, model=settings.openai_transcribe_model)
        return text or None
    except Exception as e:
        log.warning("transcribe.openai_failed", video=video_id, err=str(e)[:200])
        return None


def _transcribe_local(audio_path: str, video_id: str, language: str) -> str | None:
    size = os.path.getsize(audio_path)
    if size > _AUDIO_MAX_BYTES:
        log.warning("whisper.audio_too_large", video=video_id, bytes=size)
        return None
    try:
        model = _get_whisper_model()
        segments, _info = model.transcribe(
            audio_path,
            language=language if language else None,
            beam_size=1,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text or None
    except Exception as e:
        log.warning("whisper.transcribe_failed", video=video_id, err=str(e)[:200])
        return None


def fetch_transcript_via_whisper(video_id: str, language: str = "en") -> str | None:
    """Download audio + transcribe, using the configured backend
    (settings.transcribe_backend: "openai" | "local" | "none").
    Returns None when disabled or on any failure."""
    backend = (settings.transcribe_backend or "openai").lower()
    if backend == "none":
        return None
    if backend == "local" and not settings.enable_local_whisper:
        log.info("transcribe.local_disabled", video=video_id)
        return None
    if backend == "openai" and not settings.openai_api_key:
        log.info("transcribe.openai_no_key", video=video_id)
        return None

    with tempfile.TemporaryDirectory() as td:
        audio_path = _download_audio(video_id, td)
        if audio_path is None:
            return None
        if backend == "openai":
            return _transcribe_openai(audio_path, video_id)
        return _transcribe_local(audio_path, video_id, language)
