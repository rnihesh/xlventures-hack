"""Per-org integration connectors (SES, Slack, Google).

Each org configures outbound channels independently. The ``org_connectors``
table holds one row per ``(org_id, kind)`` where ``kind`` is one of ``ses``,
``slack``, or ``google``, with a JSONB ``config`` blob whose shape depends on
the kind:

  * ``ses``    -> {"sender_email": ...}
  * ``slack``  -> {"webhook_url": ...}
  * ``google`` -> {"access_token": ..., "refresh_token": ..., "expiry": ...,
                   "email": ...}

``status`` is a short human label (e.g. ``connected``, ``not_configured``) and
``updated_at`` tracks the last write. Everything is idempotent (IF NOT EXISTS)
so the migration is safe to re-run.

Revision ID: 0007_connectors
Revises: 0006_tenancy
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision = "0007_connectors"
down_revision = "0006_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_connectors (
            org_id      TEXT NOT NULL,
            kind        TEXT NOT NULL,
            config      JSONB NOT NULL DEFAULT '{}'::jsonb,
            status      TEXT NOT NULL DEFAULT 'not_configured',
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, kind)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_org_connectors_org "
        "ON org_connectors (org_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_org_connectors_org")
    op.execute("DROP TABLE IF EXISTS org_connectors")
