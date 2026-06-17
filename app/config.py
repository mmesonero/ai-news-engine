from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev")
    log_level: str = Field(default="INFO")
    # Set false for a read-only viewer (don't start the cron pipeline in-process).
    enable_scheduler: bool = Field(default=True)

    database_url: str = Field(
        default="postgresql+asyncpg://ai:ai@localhost:5432/ai_news",
        description="Async SQLAlchemy URL used by the app at runtime. In the cloud this comes "
        "from the DATABASE_URL secret (Neon).",
    )
    sync_database_url: str = Field(
        default="postgresql+psycopg2://ai:ai@localhost:5432/ai_news",
        description="Sync URL used by Alembic. In the cloud: SYNC_DATABASE_URL secret (Neon).",
    )

    openai_api_key: str = Field(default="")
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    openai_llm_model: str = Field(default="gpt-4o-mini")
    openai_transcribe_model: str = Field(
        default="gpt-4o-transcribe",
        description="OpenAI speech-to-text model: gpt-4o-transcribe | gpt-4o-mini-transcribe | whisper-1",
    )

    # Public site base — where the static news pages are published. Telegram links
    # and the index cards point at per-story detail pages under this URL.
    public_site_base: str = Field(default="https://mmesonero.github.io/ai-news")

    # Telegram delivery (optional). Secrets come from env, never a committed file.
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    telegram_max_items: int = Field(default=12, description="Max stories per daily briefing message set.")

    # Weekly email digest (optional). SMTP — works with Gmail (smtp.gmail.com + App
    # Password) or Resend (smtp.resend.com, user="resend", pass=API key). Secrets only.
    email_host: str = Field(default="")
    email_port: int = Field(default=587)
    email_user: str = Field(default="")
    email_password: str = Field(default="")
    email_from: str = Field(default="", description="From address; defaults to email_user if blank.")
    email_to: str = Field(default="", description="Comma-separated recipient list.")
    email_max_items: int = Field(default=15, description="Hard cap for stories in the weekly digest (top 10 + extra 'alta').")
    telegram_channel_url: str = Field(
        default="https://t.me/+ImA4ksuUUbMzMzFk",
        description="Public Telegram channel invite — shown as a CTA in the email footer.",
    )

    dedup_threshold: float = Field(default=0.90)
    cluster_threshold: float = Field(default=0.82)
    dedup_lookback_days: int = Field(default=14)
    pipeline_cron: str = Field(default="0 6 * * *")
    retention_days: int = Field(default=30, description="Delete raw_content older than this.")
    retention_cron: str = Field(default="30 6 * * *", description="When to run cleanup (after pipeline).")

    # Audio transcription (for videos without subtitles):
    #   "openai" → OpenAI transcription API   |   "none" → disabled
    transcribe_backend: str = Field(default="openai")
    whisper_max_per_run: int = Field(default=15, description="Cap transcription invocations per pipeline run.")

    embedding_dim: int = 1536


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
