"""Initial schema: pgvector extension, runs and recommendations tables.

Revision ID: 0001_init
Revises:
Create Date: 2026-06-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector for future embedding columns / similarity search.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- runs ----------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("signal", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- recommendations -----------------------------------------------------
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        # Full explainable recommendation object (see contracts/recommendation.schema.json).
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_recommendations_run_id",
        "recommendations",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommendations_run_id", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_table("runs")
    # Intentionally do not drop the vector extension (may be shared).
