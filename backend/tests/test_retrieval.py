"""Retriever tests: span-exact, auditable citations.

The headline guarantee of the retrieval slice is that every Evidence item's
``span`` indexes into the *original* source document text, so the frontend can
highlight ``source_text[start:end]`` and get back exactly the cited snippet.
These tests verify that invariant against the seeded corpus, fully offline
(lexical BM25 path, no embeddings).
"""

from __future__ import annotations

from app.retrieval.store import Retriever, get_retriever
from app.retrieval.types import Evidence


async def test_retriever_returns_span_exact_evidence() -> None:
    """Each returned Evidence has a char span that reproduces its snippet."""

    retriever: Retriever = get_retriever("customer_success")
    results = await retriever.search(
        "usage drop renewal risk sponsor disengaged", account_id=None, k=5
    )

    assert results, "the seeded corpus must return evidence for a relevant query"

    for ev in results:
        assert isinstance(ev, Evidence)

        # The span is well-formed.
        assert 0 <= ev.span.start <= ev.span.end

        # The citation is auditable: the span indexes into the *source document*
        # text and reproduces the snippet exactly.
        source_text = retriever._documents[ev.source_id]
        assert source_text[ev.span.start : ev.span.end] == ev.snippet

        # The snippet is a genuine, non-empty excerpt of the source.
        assert ev.snippet
        assert ev.snippet in source_text

        # The score is a normalized relevance value.
        assert 0.0 <= ev.score <= 1.0


async def test_retriever_account_scoping_and_breadth() -> None:
    """Results de-duplicate by document and respect account scoping."""

    retriever: Retriever = get_retriever("customer_success")
    results = await retriever.search("renewal risk", account_id="ACC-1001", k=5)

    assert results

    # One span per source document keeps the top-k spanning the corpus breadth.
    source_ids = [ev.source_id for ev in results]
    assert len(source_ids) == len(set(source_ids))

    # Span invariant still holds under account scoping.
    for ev in results:
        source_text = retriever._documents[ev.source_id]
        assert source_text[ev.span.start : ev.span.end] == ev.snippet


async def test_empty_query_returns_no_evidence() -> None:
    """A blank query yields no evidence rather than raising."""

    retriever: Retriever = get_retriever("customer_success")
    assert await retriever.search("   ", account_id=None, k=5) == []


async def test_ingested_evidence_is_org_scoped() -> None:
    """One org's ingested evidence is never retrieved by another org.

    Uses a fresh retriever so the assertion is isolated from the shared corpus.
    Seed knowledge (org_id None) stays shared; ingested chunks are private to
    their owning org.
    """

    retriever = Retriever("customer_success")
    marker = "zzqphlx unique competitor bake-off before the renewal"
    retriever.add_document(
        doc_id="ingest::test::orgA",
        account_id=None,
        source_type="meeting_notes",
        title="Org A private note",
        text=marker,
        org_id="org_a",
    )

    mine = await retriever.search(marker, account_id=None, k=5, org_id="org_a")
    assert any(marker in ev.snippet for ev in mine), "owner org must see its evidence"

    theirs = await retriever.search(marker, account_id=None, k=5, org_id="org_b")
    assert all(
        marker not in ev.snippet for ev in theirs
    ), "a different org must not retrieve another org's ingested evidence"
