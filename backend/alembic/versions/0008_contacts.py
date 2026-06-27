"""Org-scoped contacts (recipients for targeted outreach).

Contacts are the people an org reaches out to: a name, an email, an optional
linked account, and a free-text role. They back the email recipient picker so a
user (or the chat agent) can send a recommendation to a saved person by name
instead of retyping an address. One row per contact, scoped by ``org_id`` so one
org never sees another's contacts.

Everything is idempotent (IF NOT EXISTS) so the migration is safe to re-run.

Revision ID: 0008_contacts
Revises: 0007_connectors
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision = "0008_contacts"
down_revision = "0007_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id          TEXT PRIMARY KEY,
            org_id      TEXT NOT NULL,
            name        TEXT NOT NULL,
            email       TEXT NOT NULL,
            account_id  TEXT,
            role        TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_org ON contacts (org_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contacts_org")
    op.execute("DROP TABLE IF EXISTS contacts")
