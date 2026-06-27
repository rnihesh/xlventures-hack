"""Per-org domain pack overrides (configurable rules and actions).

Each org can tailor a domain pack without forking it: the base pack ships in
``domain_packs/<domain>.yaml`` and stays intact, while an org's edits to the
policy rules and action catalog are stored here as an additive JSONB override.
The policy engine and planner read the effective pack (base merged with the
org override) for the current org.

The ``pack_overrides`` table holds one row per ``(org_id, domain)`` with an
``overrides`` JSONB blob shaped like ``{"policies": [...], "actions": [...]}``.
Everything is idempotent (IF NOT EXISTS) so the migration is safe to re-run.

Revision ID: 0009_pack_overrides
Revises: 0008_contacts
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision = "0009_pack_overrides"
down_revision = "0008_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pack_overrides (
            org_id      TEXT NOT NULL,
            domain      TEXT NOT NULL,
            overrides   JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, domain)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pack_overrides_org "
        "ON pack_overrides (org_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pack_overrides_org")
    op.execute("DROP TABLE IF EXISTS pack_overrides")
