"""add theme + importance_tier to processed_content

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-15

Thematic categories ported from Executive Lab's classifier (9 cats).
- theme: one of nuevo_modelo, herramienta_nueva, nueva_funcionalidad,
  movimiento_empresarial, caso_practico, insight_negocio, ejemplo_uso,
  noticia_relevante, irrelevante (irrelevante implies is_noise=true).
- importance_tier: alta | media | baja (coarse complement to importance_score 0-100).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processed_content", sa.Column("theme", sa.Text, nullable=True))
    op.add_column("processed_content", sa.Column("importance_tier", sa.Text, nullable=True))
    op.create_index("ix_processed_content_theme", "processed_content", ["theme"])
    op.create_index(
        "ix_processed_content_importance_tier", "processed_content", ["importance_tier"]
    )


def downgrade() -> None:
    op.drop_index("ix_processed_content_importance_tier", table_name="processed_content")
    op.drop_index("ix_processed_content_theme", table_name="processed_content")
    op.drop_column("processed_content", "importance_tier")
    op.drop_column("processed_content", "theme")
