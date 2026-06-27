"""OpenAI usage accounting and last-login tracking (admin panel).

``usage_events`` records token usage per org so the admin panel can show how
much each org is spending on OpenAI. One row per (request, kind, model) holds
the input/output/total tokens and the computed dollar cost. A ``users.last_login_at``
column lets the panel show recency of activity. Everything is idempotent.

Revision ID: 0011_usage_events
Revises: 0010_org_packs
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

revision = "0011_usage_events"
down_revision = "0010_org_packs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id            BIGSERIAL PRIMARY KEY,
            org_id        TEXT NOT NULL,
            kind          TEXT NOT NULL,
            model         TEXT NOT NULL DEFAULT '',
            input_tokens  INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens  INTEGER NOT NULL DEFAULT 0,
            cost_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS usage_events_org_time_idx "
        "ON usage_events (org_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS usage_events_time_idx "
        "ON usage_events (created_at DESC);"
    )
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_events;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login_at;")
