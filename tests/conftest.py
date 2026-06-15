"""Test fixtures. These tests are deliberately database-free so they run anywhere
without provisioning postgres+pgvector."""
from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SYNC_DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")
