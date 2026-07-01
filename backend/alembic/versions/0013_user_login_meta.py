"""User login metadata for the admin panel.

Records how and from where a user signed up and last authenticated, so the admin
panel can show auth method (password / google / passkey) and IP. Idempotent.

Revision ID: 0013_user_login_meta
Revises: 0012_passkeys
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op

revision = "0013_user_login_meta"
down_revision = "0012_passkeys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider TEXT DEFAULT 'password';")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS signup_ip TEXT;")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_ip TEXT;")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_method TEXT;")


def downgrade() -> None:
    for col in ("auth_provider", "signup_ip", "last_login_ip", "last_login_method"):
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {col};")
