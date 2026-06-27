"""Per-org uploaded domain packs (extensibility: a new domain in 60 seconds).

An org can add a brand new vertical at runtime by uploading a domain pack YAML.
Unlike ``pack_overrides`` (which tailors an existing base pack), an org pack is a
whole new domain authored by the org: it is validated against the pack schema,
stored here, surfaced in the domain list, and a decision can be run on it
immediately. The base packs that ship in ``domain_packs/<domain>.yaml`` are never
touched, and one org never sees another org's uploaded packs.

The ``org_packs`` table holds one row per ``(org_id, domain)`` with the raw
``yaml`` text (the source of truth the org authored) and a ``parsed`` JSONB blob
(the validated pack, cached so reads never re-parse). Everything is idempotent
(IF NOT EXISTS) so the migration is safe to re-run.

Revision ID: 0010_org_packs
Revises: 0009_pack_overrides
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision = "0010_org_packs"
down_revision = "0009_pack_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_packs (
            org_id      TEXT NOT NULL,
            domain      TEXT NOT NULL,
            name        TEXT NOT NULL DEFAULT '',
            yaml        TEXT NOT NULL DEFAULT '',
            parsed      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, domain)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_org_packs_org ON org_packs (org_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_org_packs_org")
    op.execute("DROP TABLE IF EXISTS org_packs")
