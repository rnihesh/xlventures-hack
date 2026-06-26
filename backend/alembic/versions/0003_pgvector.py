"""pgvector: document chunk embeddings + episode embeddings.

Enables the ``vector`` extension and adds the durable vector store backing
semantic retrieval:

  * ``document_chunks`` holds one row per citeable chunk with a
    ``vector(1536)`` embedding (matching ``text-embedding-3-small``) plus exact
    character spans, so cosine-distance search (``<=>``) is span-citation safe.
  * ``episodes`` gains an ``embedding vector(1536)`` column so learning memory
    recall can run as a vector search instead of in-memory lexical similarity.

Both vector columns get an HNSW index using ``vector_cosine_ops``. Everything is
idempotent (IF NOT EXISTS) so the migration is safe to re-run.

Revision ID: 0003_pgvector
Revises: 0002_persistence
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision = "0003_pgvector"
down_revision = "0002_persistence"
branch_labels = None
depends_on = None

_EMBED_DIM = 1536


def upgrade() -> None:
    # pgvector extension (no-op if already installed).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- document_chunks: vector store for span-cited retrieval -------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id          TEXT PRIMARY KEY,
            doc_id      TEXT NOT NULL,
            account_id  TEXT,
            domain      TEXT NOT NULL,
            source_type TEXT,
            title       TEXT,
            text        TEXT NOT NULL,
            start_char  INTEGER NOT NULL DEFAULT 0,
            end_char    INTEGER NOT NULL DEFAULT 0,
            embedding   vector({_EMBED_DIM}),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_domain "
        "ON document_chunks (domain)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_account_id "
        "ON document_chunks (account_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    # --- episodes: add a vector column for similarity recall -----------------
    op.execute(
        f"ALTER TABLE episodes ADD COLUMN IF NOT EXISTS embedding vector({_EMBED_DIM})"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_episodes_embedding "
        "ON episodes USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_episodes_embedding")
    op.execute("ALTER TABLE episodes DROP COLUMN IF EXISTS embedding")

    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_account_id")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_domain")
    op.execute("DROP TABLE IF EXISTS document_chunks")
    # Leave the extension installed: other objects may depend on it.
