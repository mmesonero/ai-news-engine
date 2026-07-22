from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev")
    log_level: str = Field(default="INFO")
    # Opt-in only: serving the FastAPI app does NOT start the in-process cron unless
    # this is true. The cloud runs the pipeline via GitHub Actions + direct module
    # calls, so this stays false and a local `uvicorn` never fires a real pipeline.
    enable_scheduler: bool = Field(default=False)
    # If set, the /admin/* endpoints require header `X-Admin-Token: <this>`. Unset
    # (default) keeps them open for local dev — they aren't served in the cloud.
    admin_token: str = Field(default="")

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
    telegram_min_score: int = Field(default=65, description="Only push stories with boosted score >= this.")

    # Weekly email digest (optional). SMTP — works with Gmail (smtp.gmail.com + App
    # Password) or Resend (smtp.resend.com, user="resend", pass=API key). Secrets only.
    email_host: str = Field(default="")
    email_port: int = Field(default=587)
    email_user: str = Field(default="")
    email_password: str = Field(default="")
    email_from: str = Field(default="", description="From address; defaults to email_user if blank.")
    email_to: str = Field(default="", description="Comma-separated recipient list.")
    email_max_items: int = Field(default=15, description="Hard cap for stories in the weekly digest (top 10 + extra 'high').")
    telegram_channel_url: str = Field(
        default="https://t.me/+ImA4ksuUUbMzMzFk",
        description="Public Telegram channel invite — shown as a CTA in the email footer.",
    )
    email_address: str = Field(
        default="",
        description="Physical/postal address shown in the email footer (RGPD/LSSI for public sends).",
    )

    # Public newsletter via Brevo (optional). When BOTH are set, the weekly digest is
    # sent as a Brevo campaign to the contact list (Brevo stores subscribers securely,
    # adds a compliant 1-click unsubscribe, manages bounces). Falls back to SMTP if unset.
    # Sender must be a VERIFIED sender in Brevo (uses email_from / email_user).
    brevo_api_key: str = Field(default="", description="Brevo API key (api-key header). Secret only.")
    brevo_list_id: int = Field(default=0, description="Brevo contact-list id the campaign targets.")

    # LinkedIn DRAFTS (copy-paste, no LinkedIn API). The engine writes a ready-to-paste
    # post and sends it to Telegram for you to approve + paste manually.
    linkedin_min_score: int = Field(default=85, description="Breaking draft only for a top story with boosted score >= this.")
    linkedin_draft_chat_id: str = Field(
        default="",
        description="Telegram chat for LinkedIn drafts (your DM with the bot). Falls back to "
        "telegram_chat_id — set it to keep drafts OFF the public channel.",
    )

    dedup_threshold: float = Field(default=0.90)
    cluster_threshold: float = Field(default=0.82)
    dedup_lookback_days: int = Field(default=14)
    pipeline_cron: str = Field(default="0 6 * * *")
    retention_days: int = Field(default=30, description="Delete raw_content older than this.")
    retention_cron: str = Field(default="30 6 * * *", description="When to run cleanup (after pipeline).")

    # Audio transcription (for videos without subtitles):
    #   "openai" → OpenAI transcription API   |   "none" → disabled
    # Default "none": YouTube sources were dropped to cut token spend, so there
    # are no videos to transcribe. Set "openai" again only if YT sources return.
    transcribe_backend: str = Field(default="none")
    whisper_max_per_run: int = Field(default=15, description="Cap transcription invocations per pipeline run.")

    embedding_dim: int = 1536

    @field_validator(
        "email_port", "brevo_list_id", "telegram_min_score", "telegram_max_items",
        "email_max_items", "linkedin_min_score", "whisper_max_per_run", mode="before",
    )
    @classmethod
    def _blank_int_to_default(cls, v, info):
        """An unset GitHub secret is injected as an empty string. Don't let that crash
        int parsing — fall back to the field's declared default. A set-but-blank value
        is logged (distinct from unset) so a mis-set secret isn't silently swallowed."""
        if v is None:
            return cls.model_fields[info.field_name].default
        if isinstance(v, str) and v.strip() == "":
            logging.getLogger(__name__).warning(
                "config.blank_value_substituted field=%s (using default)", info.field_name
            )
            return cls.model_fields[info.field_name].default
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
