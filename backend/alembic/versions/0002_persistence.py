"""Persistence: episodes + outcomes tables, run/recommendation augmentations.

Adds the durable backing for the learning loop (``episodes`` and an append-only
``outcomes`` audit log) and rounds out the ``runs`` / ``recommendations`` tables
with a JSONB payload, an ``updated_at`` timestamp, and useful query indexes.

Revision ID: 0002_persistence
Revises: 0001_init
Create Date: 2026-06-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers used by Alembic.
revision = "0002_persistence"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- runs augmentations --------------------------------------------------
    op.add_column("runs", sa.Column("payload", postgresql.JSONB(), nullable=True))
    op.add_column(
        "runs",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_runs_account_id", "runs", ["account_id"])
    op.create_index("ix_runs_domain", "runs", ["domain"])

    # --- recommendations augmentations --------------------------------------
    op.add_column(
        "recommendations",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_recommendations_account_id", "recommendations", ["account_id"]
    )

    # --- episodes ------------------------------------------------------------
    # One row per decision episode. Structured columns drive indexing/queries;
    # the full JSONB ``payload`` round-trips losslessly into Episode models.
    op.create_table(
        "episodes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("situation", sa.Text(), nullable=False, server_default=""),
        sa.Column("action_key", sa.Text(), nullable=True),
        sa.Column("recommendation", postgresql.JSONB(), nullable=True),
        sa.Column("preferred_action_key", sa.Text(), nullable=True),
        sa.Column("phase", sa.Text(), nullable=False, server_default="live"),
        sa.Column("outcome", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_episodes_account_id", "episodes", ["account_id"])
    op.create_index("ix_episodes_domain", "episodes", ["domain"])
    op.create_index("ix_episodes_status", "episodes", ["status"])

    # --- outcomes (append-only audit log) -----------------------------------
    op.create_table(
        "outcomes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("episode_id", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_outcomes_episode_id", "outcomes", ["episode_id"])


def downgrade() -> None:
    op.drop_index("ix_outcomes_episode_id", table_name="outcomes")
    op.drop_table("outcomes")

    op.drop_index("ix_episodes_status", table_name="episodes")
    op.drop_index("ix_episodes_domain", table_name="episodes")
    op.drop_index("ix_episodes_account_id", table_name="episodes")
    op.drop_table("episodes")

    op.drop_index("ix_recommendations_account_id", table_name="recommendations")
    op.drop_column("recommendations", "updated_at")

    op.drop_index("ix_runs_domain", table_name="runs")
    op.drop_index("ix_runs_account_id", table_name="runs")
    op.drop_column("runs", "updated_at")
    op.drop_column("runs", "payload")
