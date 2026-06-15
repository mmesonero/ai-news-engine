"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-30

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("config_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("url", name="uq_sources_url"),
    )
    op.create_index("ix_sources_active", "sources", ["active"])
    op.create_index("ix_sources_type", "sources", ["type"])

    op.create_table(
        "raw_content",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source_id", sa.BigInteger, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("author", sa.Text, nullable=True),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=False, server_default="{}"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_raw_source_external"),
        sa.UniqueConstraint("url", name="uq_raw_url"),
    )
    op.create_index("ix_raw_content_hash", "raw_content", ["content_hash"])
    op.create_index("ix_raw_published_at", "raw_content", ["published_at"])

    op.create_table(
        "embeddings",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("raw_content_id", sa.BigInteger, sa.ForeignKey("raw_content.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "content_clusters",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("cluster_topic", sa.Text, nullable=True),
        sa.Column("representative_content_id", sa.BigInteger, sa.ForeignKey("raw_content.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "cluster_items",
        sa.Column("cluster_id", sa.BigInteger, sa.ForeignKey("content_clusters.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("raw_content_id", sa.BigInteger, sa.ForeignKey("raw_content.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("similarity_score", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("ix_cluster_items_content", "cluster_items", ["raw_content_id"])

    op.create_table(
        "processed_content",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("raw_content_id", sa.BigInteger, sa.ForeignKey("raw_content.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("cleaned_summary", sa.Text, nullable=True),
        sa.Column("key_topics", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("novelty_score", sa.Integer, nullable=True),
        sa.Column("importance_score", sa.Integer, nullable=True),
        sa.Column("linkedin_potential_score", sa.Integer, nullable=True),
        sa.Column("business_impact_score", sa.Integer, nullable=True),
        sa.Column("ai_generated_insights", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("linkedin_angles", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("rejected_reason", sa.Text, nullable=True),
        sa.Column("is_noise", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_processed_importance", "processed_content", ["importance_score"])
    op.create_index("ix_processed_linkedin", "processed_content", ["linkedin_potential_score"])
    op.create_index("ix_processed_is_noise", "processed_content", ["is_noise"])

    op.execute(
        "CREATE INDEX ix_embeddings_vec ON embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vec;")
    op.drop_table("processed_content")
    op.drop_table("cluster_items")
    op.drop_table("content_clusters")
    op.drop_table("embeddings")
    op.drop_table("raw_content")
    op.drop_table("sources")
