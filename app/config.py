from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+asyncpg://ai:ai@db:5432/ai_news",
        description="Async SQLAlchemy URL used by the app at runtime.",
    )
    sync_database_url: str = Field(
        default="postgresql+psycopg2://ai:ai@db:5432/ai_news",
        description="Sync URL used by Alembic.",
    )

    openai_api_key: str = Field(default="")
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    openai_llm_model: str = Field(default="gpt-4o-mini")
    openai_transcribe_model: str = Field(
        default="gpt-4o-transcribe",
        description="OpenAI speech-to-text model: gpt-4o-transcribe | gpt-4o-mini-transcribe | whisper-1",
    )

    # Telegram delivery (optional). Secrets come from env, never a committed file.
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    telegram_max_items: int = Field(default=12, description="Max stories per daily briefing message set.")

    dedup_threshold: float = Field(default=0.90)
    cluster_threshold: float = Field(default=0.82)
    dedup_lookback_days: int = Field(default=14)
    pipeline_cron: str = Field(default="0 6 * * *")
    retention_days: int = Field(default=30, description="Delete raw_content older than this.")
    retention_cron: str = Field(default="30 6 * * *", description="When to run cleanup (after pipeline).")

    # Transcript fallback config.
    # Backend for audio transcription when no subtitles exist:
    #   "openai" → OpenAI transcription API (no CPU; works on GitHub Actions / cloud)
    #   "local"  → faster-whisper on CPU (free, heavy; respects enable_local_whisper)
    #   "none"   → disable audio transcription entirely
    transcribe_backend: str = Field(default="openai")
    enable_local_whisper: bool = Field(default=True)
    whisper_model: str = Field(default="base", description="faster-whisper model: tiny|base|small|medium|large-v3")
    whisper_max_per_run: int = Field(default=15, description="Cap transcription invocations per pipeline run.")

    embedding_dim: int = 1536


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
