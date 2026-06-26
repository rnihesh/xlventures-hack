"""Tests for the pgvector wiring: deterministic offline embeddings, the ingest
chunk/embed pipeline, and the retriever's pgvector code path (exercised with a
fake repository so no database is required).
"""

from __future__ import annotations

from app.ingest import run_ingest
from app.repositories.episodes import _vector_literal
from app.repositories.vectors import vector_literal
from app.retrieval.embeddings import EMBED_DIM, embed_for_index, hash_embed
from app.retrieval.store import get_retriever
from app.retrieval.types import Evidence


def test_hash_embedding_is_deterministic_and_correct_dim() -> None:
    a = hash_embed(["usage drop renewal risk"])
    b = hash_embed(["usage drop renewal risk"])
    assert a is not None and b is not None
    assert a.shape == (1, EMBED_DIM)
    # Deterministic across calls (so ingest and query vectors match offline).
    assert (a == b).all()


async def test_embed_for_index_offline_uses_hash() -> None:
    matrix, method = await embed_for_index(["sponsor disengaged", "seats expanded"])
    assert method == "hash"  # no OpenAI key in the test environment
    assert matrix is not None
    assert matrix.shape == (2, EMBED_DIM)


def test_vector_literal_formats_pgvector_text() -> None:
    assert vector_literal([0.5, -1.0, 2.0]) == "[0.5,-1,2]"
    assert _vector_literal([0.5, -1.0]) == "[0.5,-1]"
    assert _vector_literal(None) is None
    assert _vector_literal([]) is None


async def test_ingest_offline_chunks_and_embeds() -> None:
    """Offline ingest chunks and embeds without writing (no DATABASE_URL)."""
    payload = await run_ingest(["customer_success"], dry_run=True)
    assert payload["mode"] == "validate"
    assert payload["embedding_dim"] == EMBED_DIM
    cs = payload["domains"][0]
    assert cs["chunks"] > 0
    assert cs["embed_method"] == "hash"
    assert cs["written"] == 0


class _FakeChunkRepo:
    """Minimal stand-in for DocumentChunkRepository over a retriever's chunks."""

    def __init__(self, retriever) -> None:
        self._retriever = retriever
        self.last_account_id = "unset"

    async def search(
        self, embedding, *, account_id=None, domain="customer_success", org_id="org_demo", k=20
    ):
        self.last_account_id = account_id
        self.last_org_id = org_id
        rows = []
        for chunk in self._retriever._chunks:
            if account_id is not None and chunk.account_id not in (account_id, None):
                continue
            rows.append({"id": chunk.chunk_id, "similarity": 0.9})
            if len(rows) >= k:
                break
        return rows


async def test_retriever_pgvector_path_produces_span_exact_evidence() -> None:
    """When a pgvector backend is bound, results stay span-exact and scoped."""
    retriever = get_retriever("customer_success")
    fake = _FakeChunkRepo(retriever)
    # Bind the fake backend directly (skips get_pool / DB).
    retriever._pg_repo = fake
    retriever._pg_checked = True
    try:
        results = await retriever.search(
            "renewal risk sponsor", account_id="ACC-1001", k=5
        )
        assert results, "pgvector path must return evidence"
        assert fake.last_account_id == "ACC-1001"
        for ev in results:
            assert isinstance(ev, Evidence)
            source_text = retriever._documents[ev.source_id]
            assert source_text[ev.span.start : ev.span.end] == ev.snippet
    finally:
        # Reset so other tests use the default (in-memory/lexical) path.
        retriever._pg_repo = None
        retriever._pg_checked = False
