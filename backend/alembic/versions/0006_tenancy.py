"""Multi-tenant scoping: accounts table plus org_id on all domain data.

Tenancy model: every user belongs to one org (see the auth slice, revision
0005_auth), and all domain data is scoped by ``org_id``. A special ``org_demo``
org owns every existing seed row, so this migration:

  * creates the ``accounts`` table (accounts move into the database, keyed by
    ``(org_id, account_id)`` with a JSONB payload), and
  * adds a nullable ``org_id`` column to ``runs``, ``recommendations``,
    ``episodes``, ``outcomes``, ``chat_sessions``, and ``document_chunks``,
    backfills existing rows to ``org_demo``, and indexes ``(org_id, ...)`` so
    per-org reads stay cheap.

Everything is idempotent (IF NOT EXISTS) so the migration is safe to re-run.

Revision ID: 0006_tenancy
Revises: 0005_auth
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision = "0006_tenancy"
down_revision = "0005_auth"
branch_labels = None
depends_on = None

_DEMO_ORG = "org_demo"

# Tables that gain a nullable org_id (backfilled to the demo org).
_SCOPED_TABLES = (
    "runs",
    "recommendations",
    "episodes",
    "outcomes",
    "chat_sessions",
    "document_chunks",
)


def upgrade() -> None:
    # --- accounts: domain accounts move into the database --------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            org_id      TEXT NOT NULL,
            account_id  TEXT NOT NULL,
            domain      TEXT NOT NULL,
            payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, account_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_accounts_org_domain "
        "ON accounts (org_id, domain)"
    )

    # --- org_id on every scoped table ---------------------------------------
    for table in _SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS org_id TEXT")
        # Backfill existing rows to the demo org that owns the seed data.
        op.execute(
            f"UPDATE {table} SET org_id = '{_DEMO_ORG}' WHERE org_id IS NULL"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_org_id ON {table} (org_id)"
        )

    # Composite indexes that match the common per-org reads.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_runs_org_account "
        "ON runs (org_id, account_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_episodes_org_domain "
        "ON episodes (org_id, domain)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_org_domain "
        "ON document_chunks (org_id, domain)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_org_updated "
        "ON chat_sessions (org_id, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_org_updated")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_org_domain")
    op.execute("DROP INDEX IF EXISTS ix_episodes_org_domain")
    op.execute("DROP INDEX IF EXISTS ix_runs_org_account")

    for table in _SCOPED_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_org_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS org_id")

    op.execute("DROP INDEX IF EXISTS ix_accounts_org_domain")
    op.execute("DROP TABLE IF EXISTS accounts")
