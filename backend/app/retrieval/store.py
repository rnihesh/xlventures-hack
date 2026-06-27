"""Hybrid retriever: lexical BM25 + optional embeddings fused with RRF.

Conforms to the frozen Retriever interface:

    class Retriever:
        async def search(query, account_id, k=5) -> list[Evidence]
    def get_retriever() -> Retriever

The corpus (seed documents) is chunked and indexed once at construction. Lexical
ranking always runs. When OpenAI embeddings are available, corpus chunks are
embedded lazily on first search and fused with the lexical ranking via
Reciprocal Rank Fusion (RRF). Offline, the retriever is lexical-only.
"""

from __future__ import annotations

import asyncio

from app.seed_data import load_documents

from .chunking import chunk_document
from .citations import build_evidence
from .embeddings import cosine_rank, embed_for_index, embed_texts, embeddings_available
from .lexical import BM25Index
from .types import Chunk, Evidence

_RRF_C = 60.0

# The org that owns the seeded in-memory corpus. Multi-tenant runs pass their
# own org_id so a run only retrieves its org's knowledge from pgvector; the
# in-memory corpus is the Demo org's seeded knowledge.
_DEMO_ORG = "org_demo"


class Retriever:
    """Hybrid lexical + (optional) embedding retriever over the seed corpus."""

    def __init__(self, domain: str = "customer_success") -> None:
        self.domain = domain
        self._documents: dict[str, str] = {}
        self._chunks: list[Chunk] = []
        self._load_corpus()

        # Lexical index is always available.
        self._bm25 = BM25Index([c.context for c in self._chunks])
        # Map chunk id -> in-memory index so pgvector hits map back to the exact
        # in-memory chunk (preserving span-exact citation construction).
        self._chunk_index = {c.chunk_id: i for i, c in enumerate(self._chunks)}

        # Embedding state (filled lazily, guarded by a lock).
        self._use_embeddings = embeddings_available()
        self._embeddings = None  # numpy matrix or None
        self._embed_lock = asyncio.Lock()
        self._embed_attempted = False

        # pgvector backend (resolved lazily). When a pool is available and the
        # document_chunks table is populated, the embedding ranking is served by
        # Postgres (cosine distance via <=>) instead of the in-memory matrix.
        self._pg_repo: object | None = None
        self._pg_checked = False

    # -- corpus -----------------------------------------------------------
    def _load_corpus(self) -> None:
        for doc in load_documents(self.domain):
            doc_id = doc["id"]
            text = doc.get("text", "") or ""
            self._documents[doc_id] = text
            self._chunks.extend(
                chunk_document(
                    doc_id=doc_id,
                    account_id=doc.get("account_id"),
                    source_type=doc.get("source_type", "document"),
                    title=doc.get("title", doc_id),
                    text=text,
                )
            )

    # -- helpers ----------------------------------------------------------
    def _candidate_indices(
        self, account_id: str | None, org_id: str = _DEMO_ORG
    ) -> list[int]:
        """Indices eligible for this query.

        Tenant scoping first: a chunk is visible only when it is shared seed
        knowledge (``chunk.org_id is None``) or owned by the querying ``org_id``,
        so one org never retrieves another org's ingested evidence. Within that,
        account-scoped queries additionally see that account's chunks plus all
        shared (account_id is None) knowledge.
        """

        def _org_ok(c: Chunk) -> bool:
            return c.org_id is None or c.org_id == org_id

        if account_id is None:
            return [i for i, c in enumerate(self._chunks) if _org_ok(c)]
        return [
            i
            for i, c in enumerate(self._chunks)
            if _org_ok(c) and (c.account_id == account_id or c.account_id is None)
        ]

    async def _ensure_vector_backend(self) -> object | None:
        """Bind the pgvector backend if a populated table is reachable.

        Resolved at most once. Returns the DocumentChunkRepository when a pool
        is configured and ``document_chunks`` has rows for this domain, else
        ``None`` (the caller then uses the in-memory/lexical path).
        """
        if self._pg_checked:
            return self._pg_repo
        async with self._embed_lock:
            if self._pg_checked:
                return self._pg_repo
            self._pg_checked = True
            try:
                from app.deps import get_pool
                from app.repositories.vectors import DocumentChunkRepository

                pool = await get_pool()
                if pool is not None:
                    repo = DocumentChunkRepository(pool)
                    if repo.enabled and await repo.count(self.domain) > 0:
                        self._pg_repo = repo
            except Exception:  # noqa: BLE001 - any failure degrades to in-memory
                self._pg_repo = None
            return self._pg_repo

    async def _embedding_order(
        self,
        query: str,
        account_id: str | None,
        allowed: set[int],
        pool: int,
        org_id: str = _DEMO_ORG,
    ) -> list[int]:
        """Rank candidate chunk indices by embedding similarity.

        Uses pgvector when available (offline-safe hash or OpenAI query vector),
        otherwise the lazily-built in-memory embedding matrix. Results are scoped
        to ``org_id`` on the pgvector path. Returns chunk indices (into
        ``self._chunks``) best-first, filtered to ``allowed``.
        """
        backend = await self._ensure_vector_backend()
        if backend is not None:
            q_matrix, _ = await embed_for_index([query])
            if q_matrix is None or not len(q_matrix):
                return []
            try:
                rows = await backend.search(
                    q_matrix[0].tolist(),
                    account_id=account_id,
                    domain=self.domain,
                    org_id=org_id,
                    k=pool,
                )
            except Exception:  # noqa: BLE001 - degrade to lexical only
                return []
            order: list[int] = []
            for row in rows:
                idx = self._chunk_index.get(row.get("id"))
                if idx is not None and idx in allowed:
                    order.append(idx)
            return order

        # In-memory fallback (OpenAI matrix only; lexical-only when offline).
        await self._ensure_embeddings()
        if self._use_embeddings and self._embeddings is not None:
            q_matrix = await embed_texts([query])
            if q_matrix is not None and len(q_matrix):
                ranked = cosine_rank(q_matrix[0], self._embeddings, k=len(self._chunks))
                return [i for i, _ in ranked if i in allowed][:pool]
        return []

    async def _ensure_embeddings(self) -> None:
        if not self._use_embeddings or self._embeddings is not None or self._embed_attempted:
            return
        async with self._embed_lock:
            if self._embeddings is not None or self._embed_attempted:
                return
            self._embed_attempted = True
            matrix = await embed_texts([c.context for c in self._chunks])
            if matrix is None:
                self._use_embeddings = False
            else:
                self._embeddings = matrix

    @staticmethod
    def _rrf(rank_lists: list[list[int]]) -> dict[int, float]:
        fused: dict[int, float] = {}
        for ranking in rank_lists:
            for rank, idx in enumerate(ranking):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (_RRF_C + rank + 1.0)
        return fused

    # -- public API -------------------------------------------------------
    async def search(
        self,
        query: str,
        account_id: str | None = None,
        k: int = 5,
        org_id: str = _DEMO_ORG,
    ) -> list[Evidence]:
        """Return up to ``k`` Evidence items ranked by hybrid relevance.

        ``org_id`` scopes the durable pgvector lookups so a run only retrieves
        its own org's knowledge (defaults to the Demo org that owns the seeded
        in-memory corpus).
        """
        if not query or not query.strip() or not self._chunks:
            return []

        candidates = self._candidate_indices(account_id, org_id)
        if not candidates:
            return []
        allowed = set(candidates)
        pool = max(k * 4, 20)

        # Lexical ranking (always).
        lex = [(i, s) for i, s in self._bm25.search(query, k=pool) if i in allowed]
        lex_order = [i for i, _ in lex]

        # Optional embedding ranking (pgvector when available, else in-memory).
        emb_order = await self._embedding_order(
            query, account_id, allowed, pool, org_id
        )

        # Fuse.
        if emb_order:
            fused = self._rrf([lex_order, emb_order])
            ranked_idx = sorted(fused.keys(), key=lambda i: fused[i], reverse=True)
            raw = {i: fused[i] for i in ranked_idx}
            method_norm = max(raw.values()) if raw else 1.0
        else:
            ranked_idx = lex_order
            raw = {i: s for i, s in lex}
            method_norm = max(raw.values()) if raw else 1.0

        results: list[Evidence] = []
        seen_docs: set[str] = set()
        for idx in ranked_idx:
            chunk = self._chunks[idx]
            # De-duplicate by document so the top-k spans the corpus breadth.
            if chunk.doc_id in seen_docs:
                continue
            seen_docs.add(chunk.doc_id)
            score = raw.get(idx, 0.0) / (method_norm or 1.0)
            results.append(
                build_evidence(chunk, self._documents.get(chunk.doc_id, chunk.text), score)
            )
            if len(results) >= k:
                break
        return results

    # -- live ingestion ---------------------------------------------------
    def add_document(
        self,
        *,
        doc_id: str,
        account_id: str | None,
        source_type: str,
        title: str,
        text: str,
        org_id: str | None = None,
    ) -> list[Chunk]:
        """Index a new document into the live corpus so it is retrievable now.

        Used by the ingestion connectors: the text is chunked with exact spans,
        the chunks (and their source text, for span-exact citations) are
        registered, the lexical index is rebuilt over the expanded corpus, and
        the lazily-built in-memory embedding matrix is invalidated so the new
        chunks are embedded on the next search (the pgvector path is served by
        the connector's upsert). Returns the chunks added (empty when the text
        yields none, e.g. blank input).
        """
        if not text or not text.strip():
            return []
        new_chunks = chunk_document(
            doc_id=doc_id,
            account_id=account_id,
            source_type=source_type,
            title=title,
            text=text,
            org_id=org_id,
        )
        if not new_chunks:
            return []

        self._documents[doc_id] = text
        base = len(self._chunks)
        self._chunks.extend(new_chunks)
        for offset, chunk in enumerate(new_chunks):
            self._chunk_index[chunk.chunk_id] = base + offset

        # Rebuild the lexical index so the new chunks rank immediately.
        self._bm25 = BM25Index([c.context for c in self._chunks])

        # Invalidate the in-memory embedding matrix so the expanded corpus is
        # re-embedded lazily on the next search (OpenAI path only).
        self._embeddings = None
        self._embed_attempted = False

        # Let the retriever re-bind the pgvector backend on the next search:
        # a previously-empty table may now hold these freshly written chunks.
        self._pg_checked = False
        self._pg_repo = None
        return new_chunks


# Module-level singletons keyed by domain (corpus + indexes are reusable).
_RETRIEVERS: dict[str, Retriever] = {}


def get_retriever(domain: str = "customer_success") -> Retriever:
    """Factory returning a cached hybrid Retriever for ``domain``."""
    retriever = _RETRIEVERS.get(domain)
    if retriever is None:
        retriever = Retriever(domain)
        _RETRIEVERS[domain] = retriever
    return retriever
