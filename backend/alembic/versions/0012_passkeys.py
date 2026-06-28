"""WebAuthn passkey credentials.

Stores one row per registered passkey: the credential id, the COSE public key,
and the signature counter used to detect cloned authenticators. A user can have
several passkeys (phone, laptop, security key). Everything is idempotent.

Revision ID: 0012_passkeys
Revises: 0011_usage_events
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op

revision = "0012_passkeys"
down_revision = "0011_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id            BIGSERIAL PRIMARY KEY,
            user_id       TEXT NOT NULL REFERENCES users(id),
            credential_id TEXT NOT NULL UNIQUE,
            public_key    TEXT NOT NULL,
            sign_count    BIGINT NOT NULL DEFAULT 0,
            transports    TEXT,
            label         TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at  TIMESTAMPTZ
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS webauthn_credentials_user_idx "
        "ON webauthn_credentials (user_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webauthn_credentials;")
