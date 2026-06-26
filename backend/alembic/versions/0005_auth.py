"""Auth: orgs + users tables and the Demo org / demo user seed.

Introduces multi-tenancy at the identity layer. Every user belongs to exactly
one org; all domain data is scoped by ``org_id`` (added to the domain tables by
their owning slices). This migration only owns the identity tables and seeds the
special Demo org plus its demo user (demo@niheshr.com / demo1234, pre-verified),
which owns the existing seed data.

Revision ID: 0005_auth
Revises: 0004_chat_sessions
Create Date: 2026-06-27
"""

from __future__ import annotations

import os

from alembic import op

revision = "0005_auth"
down_revision = "0004_chat_sessions"
branch_labels = None
depends_on = None

# Pre-computed bcrypt hash of "demo1234" so the migration needs no bcrypt import.
_DEMO_PASSWORD_HASH = "$2b$12$vi9pYlituojykfVi7.3WNO06NEO2sqOw7/RVJF7qJVE5Mbks9E2JO"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS orgs (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id                  TEXT PRIMARY KEY,
            email               TEXT UNIQUE NOT NULL,
            password_hash       TEXT NOT NULL,
            name                TEXT,
            role                TEXT NOT NULL DEFAULT 'member',
            org_id              TEXT NOT NULL REFERENCES orgs(id),
            email_verified      BOOLEAN NOT NULL DEFAULT FALSE,
            verification_token  TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_org_id ON users (org_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_verification_token "
        "ON users (verification_token)"
    )

    # --- Demo org + demo user seed (dev/demo only) --------------------------
    # The demo org always exists (it owns the sample accounts). The known-password
    # demo USER is only seeded in dev/demo environments so production never ships a
    # backdoor account. In prod, create the first user via the normal signup flow.
    op.execute(
        """
        INSERT INTO orgs (id, name)
        VALUES ('org_demo', 'Demo')
        ON CONFLICT (id) DO NOTHING
        """
    )
    app_env = os.environ.get("APP_ENV", "dev").strip().lower()
    if app_env not in {"production", "prod", "staging"}:
        op.execute(
            f"""
            INSERT INTO users
                (id, email, password_hash, name, role, org_id, email_verified)
            VALUES
                ('user_demo', 'demo@niheshr.com', '{_DEMO_PASSWORD_HASH}',
                 'Demo User', 'owner', 'org_demo', TRUE)
            ON CONFLICT (email) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS orgs")
