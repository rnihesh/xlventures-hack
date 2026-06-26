"""Async repository for the pgvector-backed ``document_chunks`` table.

Persists chunk embeddings and answers cosine-distance similarity queries via the
pgvector ``<=>`` operator. Like the other repositories it is a graceful no-op
when the pool is ``None`` (offline), so the retriever transparently falls back
to its in-memory lexical/embedding path.

Vectors are passed to Postgres as a text literal (``"[0.1,0.2,...]"``) and cast
with ``$N::vector`` so no extra Python driver registration (the ``pgvector``
package) is required.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import asyncpg


def vector_literal(embedding: Sequence[float]) -> str:
    """Render an embedding as a pgvector text literal: ``[v0,v1,...]``."""
    return "[" + ",".join(f"{float(x):.7g}" for x in embedding) + "]"


class DocumentChunkRepository:
    """Persist and similarity-search document chunk embeddings in pgvector."""

    def __init__(self, pool: Optional[asyncpg.Pool]) -> None:
        self._pool = pool

    @property
    def enabled(self) -> bool:
        """True when a pool is available (pgvector persistence is active)."""
        return self._pool is not None

    async def count(
        self, domain: Optional[str] = None, org_id: Optional[str] = None
    ) -> int:
        """Number of stored chunks (optionally scoped to ``domain`` / ``org_id``)."""
        if self._pool is None:
            return 0
        clauses: List[str] = []
        params: List[Any] = []
        if domain is not None:
            params.append(domain)
            clauses.append(f"domain = ${len(params)}")
        if org_id is not None:
            params.append(org_id)
            clauses.append(f"org_id = ${len(params)}")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        try:
            row = await self._pool.fetchrow(
                f"SELECT count(*) AS n FROM document_chunks{where}", *params
            )
        except asyncpg.PostgresError:
            return 0
        return int(row["n"]) if row else 0

    async def upsert_chunks(self, rows: List[Dict[str, Any]]) -> int:
        """Upsert chunk rows. Each row carries an ``embedding`` (list of floats).

        Returns the number of rows written (0 offline or for empty input).
        """
        if self._pool is None or not rows:
            return 0
        records = [
            (
                r["id"],
                r["doc_id"],
                r.get("account_id"),
                r["domain"],
                r.get("source_type"),
                r.get("title"),
                r["text"],
                int(r.get("start_char", 0)),
                int(r.get("end_char", 0)),
                vector_literal(r["embedding"]),
                r.get("org_id") or "org_demo",
            )
            for r in rows
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO document_chunks (
                    id, doc_id, account_id, domain, source_type,
                    title, text, start_char, end_char, embedding, org_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::vector, $11)
                ON CONFLICT (id) DO UPDATE SET
                    doc_id = EXCLUDED.doc_id,
                    account_id = EXCLUDED.account_id,
                    domain = EXCLUDED.domain,
                    source_type = EXCLUDED.source_type,
                    title = EXCLUDED.title,
                    text = EXCLUDED.text,
                    start_char = EXCLUDED.start_char,
                    end_char = EXCLUDED.end_char,
                    embedding = EXCLUDED.embedding,
                    org_id = EXCLUDED.org_id
                """,
                records,
            )
        return len(rows)

    async def search(
        self,
        embedding: Sequence[float],
        *,
        account_id: Optional[str] = None,
        domain: str = "customer_success",
        org_id: str = "org_demo",
        k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return up to ``k`` chunks nearest to ``embedding`` by cosine distance.

        Results are scoped to ``org_id`` so a run only retrieves its own org's
        knowledge. Account-scoped queries additionally see that account's chunks
        plus the org's shared knowledge (``account_id IS NULL``). Each row
        includes a ``similarity`` in [0, 1].
        """
        if self._pool is None:
            return []
        vec = vector_literal(embedding)
        if account_id is None:
            sql = """
                SELECT id, doc_id, account_id, source_type, title, text,
                       start_char, end_char,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM document_chunks
                WHERE domain = $2 AND org_id = $3 AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $4
            """
            rows = await self._pool.fetch(sql, vec, domain, org_id, k)
        else:
            sql = """
                SELECT id, doc_id, account_id, source_type, title, text,
                       start_char, end_char,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM document_chunks
                WHERE domain = $2
                  AND org_id = $3
                  AND (account_id = $4 OR account_id IS NULL)
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $5
            """
            rows = await self._pool.fetch(sql, vec, domain, org_id, account_id, k)
        return [dict(r) for r in rows]
