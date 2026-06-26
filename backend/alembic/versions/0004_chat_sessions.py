"""Chat sessions: persist multi-conversation chat history in Postgres.

One row per conversation. The full transcript (user/assistant turns plus the
inline tool trace) is stored as JSONB so it round-trips to the UI verbatim,
with the title and updated_at promoted to columns for listing and sorting.

Revision ID: 0004_chat_sessions
Revises: 0003_pgvector
"""

from __future__ import annotations

from alembic import op

revision = "0004_chat_sessions"
down_revision = "0003_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL DEFAULT 'New chat',
            turns       JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_updated_at "
        "ON chat_sessions (updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_sessions")
