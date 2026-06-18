"""migrate importance_tier + theme enum values from Spanish to English

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-18

The whole project went English. importance_tier (alta/media/baja) and theme
(nuevo_modelo/…) were Spanish identifiers; this rewrites existing rows to the
English values the code now uses. Idempotent: re-running maps already-English
values to themselves (no-op).
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_TIER = {"alta": "high", "media": "medium", "baja": "low"}
_THEME = {
    "nuevo_modelo": "models",
    "herramienta_nueva": "tools",
    "nueva_funcionalidad": "features",
    "movimiento_empresarial": "business",
    "caso_practico": "cases",
    "insight_negocio": "insights",
    "ejemplo_uso": "tutorials",
    "noticia_relevante": "other",
    "irrelevante": "irrelevant",
}
_THEME_DOWN = {v: k for k, v in _THEME.items()}
_TIER_DOWN = {v: k for k, v in _TIER.items()}


def _remap(col: str, mapping: dict[str, str]) -> None:
    for old, new in mapping.items():
        op.execute(
            f"UPDATE processed_content SET {col} = '{new}' WHERE {col} = '{old}'"
        )


def upgrade() -> None:
    _remap("importance_tier", _TIER)
    _remap("theme", _THEME)


def downgrade() -> None:
    _remap("importance_tier", _TIER_DOWN)
    _remap("theme", _THEME_DOWN)
