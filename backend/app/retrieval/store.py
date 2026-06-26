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
from .embeddings import cosine_rank, embed_texts, embeddings_available
from .lexical import BM25Index
from .types import Chunk, Evidence

_RRF_C = 60.0


class Retriever:
    """Hybrid lexical + (optional) embedding retriever over the seed corpus."""

    def __init__(self, domain: str = "customer_success") -> None:
        self.domain = domain
        self._documents: dict[str, str] = {}
        self._chunks: list[Chunk] = []
        self._load_corpus()

        # Lexical index is always available.
        self._bm25 = BM25Index([c.context for c in self._chunks])

        # Embedding state (filled lazily, guarded by a lock).
        self._use_embeddings = embeddings_available()
        self._embeddings = None  # numpy matrix or None
        self._embed_lock = asyncio.Lock()
        self._embed_attempted = False

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
    def _candidate_indices(self, account_id: str | None) -> list[int]:
        """Indices eligible for this query.

        Account-scoped queries see that account's chunks plus all shared
        knowledge (account_id is None: KB articles + playbooks).
        """
        if account_id is None:
            return list(range(len(self._chunks)))
        return [
            i
            for i, c in enumerate(self._chunks)
            if c.account_id == account_id or c.account_id is None
        ]

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
        self, query: str, account_id: str | None = None, k: int = 5
    ) -> list[Evidence]:
        """Return up to ``k`` Evidence items ranked by hybrid relevance."""
        if not query or not query.strip() or not self._chunks:
            return []

        candidates = self._candidate_indices(account_id)
        if not candidates:
            return []
        allowed = set(candidates)
        pool = max(k * 4, 20)

        # Lexical ranking (always).
        lex = [(i, s) for i, s in self._bm25.search(query, k=pool) if i in allowed]
        lex_order = [i for i, _ in lex]

        # Optional embedding ranking.
        emb_order: list[int] = []
        await self._ensure_embeddings()
        if self._use_embeddings and self._embeddings is not None:
            q_matrix = await embed_texts([query])
            if q_matrix is not None and len(q_matrix):
                ranked = cosine_rank(q_matrix[0], self._embeddings, k=len(self._chunks))
                emb_order = [i for i, _ in ranked if i in allowed][:pool]

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


# Module-level singletons keyed by domain (corpus + indexes are reusable).
_RETRIEVERS: dict[str, Retriever] = {}


def get_retriever(domain: str = "customer_success") -> Retriever:
    """Factory returning a cached hybrid Retriever for ``domain``."""
    retriever = _RETRIEVERS.get(domain)
    if retriever is None:
        retriever = Retriever(domain)
        _RETRIEVERS[domain] = retriever
    return retriever
