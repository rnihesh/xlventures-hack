"""Connector base: the live ingestion contract and the shared persist routine.

A connector turns a real-world interaction (a pasted meeting note, an uploaded
transcript, an email, a row of CRM data, a web snippet) into citeable, retrievable
evidence. Every connector funnels through :func:`ingest_text`, which:

1. chunks the raw text with exact character spans (so citations stay auditable),
2. registers the chunks in the live in-memory corpus via
   ``Retriever.add_document`` (immediately retrievable in the next run, fully
   offline),
3. embeds the chunks (OpenAI when ``OPENAI_API_KEY`` is set, otherwise a
   deterministic local hash embedding), and
4. upserts the embedded chunks into the pgvector ``document_chunks`` table when a
   database is configured, so semantic retrieval is served from Postgres too.

The pgvector write is best-effort: any failure (no pool, driver missing,
unreachable DB) is swallowed and the in-memory path still makes the document
retrievable. This keeps the primary file/paste path working with no network and
no database.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.retrieval.embeddings import embed_for_index
from app.retrieval.store import get_retriever

# Recognized interaction source types surfaced by ``GET /ingest/sources`` and the
# UI select. ``key`` is what callers send; ``label`` and ``description`` are for
# display. ``meeting_notes`` is first because it is the most common paste.
SOURCE_TYPES: List[Dict[str, str]] = [
    {
        "key": "meeting_notes",
        "label": "Meeting notes",
        "description": "Notes from a call, QBR, or internal sync.",
    },
    {
        "key": "call_transcript",
        "label": "Call transcript",
        "description": "Verbatim transcript of a customer or sales call.",
    },
    {
        "key": "email",
        "label": "Email",
        "description": "An inbound or outbound email thread.",
    },
    {
        "key": "support_ticket",
        "label": "Support ticket",
        "description": "A support or success ticket and its conversation.",
    },
    {
        "key": "crm_record",
        "label": "CRM record",
        "description": "Pasted CRM fields, account notes, or exported rows.",
    },
    {
        "key": "chat_message",
        "label": "Chat message",
        "description": "Slack, Teams, or in-app chat exchange.",
    },
    {
        "key": "document",
        "label": "Document",
        "description": "A general document, brief, or knowledge article.",
    },
    {
        "key": "web",
        "label": "Web result",
        "description": "Snippet captured from a live web search.",
    },
]

_SOURCE_KEYS = {s["key"] for s in SOURCE_TYPES}


def recognized_sources() -> List[Dict[str, str]]:
    """Return the recognized source-type descriptors (display order preserved)."""
    return list(SOURCE_TYPES)


def normalize_source_type(source_type: Optional[str]) -> str:
    """Map an arbitrary source-type string onto a recognized key.

    Unknown or blank values fall back to ``document`` so ingestion never rejects
    a usable payload purely on a label mismatch.
    """
    key = (source_type or "").strip().lower().replace(" ", "_")
    return key if key in _SOURCE_KEYS else "document"


@dataclass
class IngestResult:
    """Outcome of a single ingestion: what was written and where."""

    ok: bool
    chunks_written: int
    ids: List[str] = field(default_factory=list)
    doc_id: str = ""
    account_id: Optional[str] = None
    source_type: str = "document"
    title: str = ""
    domain: str = "customer_success"
    embed_method: str = "none"
    persisted: str = "memory"  # "pgvector+memory" | "memory" | "none"
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _make_doc_id(source_type: str) -> str:
    """Generate a collision-free document id for an ingested interaction."""
    return f"ingest::{source_type}::{uuid.uuid4().hex[:12]}"


async def _persist_pgvector(
    domain: str,
    chunks: List[Any],
    matrix: Any,
) -> int:
    """Best-effort upsert of embedded chunks into pgvector. Returns rows written.

    Returns 0 (and never raises) when no pool is configured, the driver/repo is
    unavailable, or the write fails: the in-memory path already made the document
    retrievable, so the database write is a durability bonus, not a requirement.
    """
    if matrix is None or not len(chunks):
        return 0
    try:
        from app.deps import get_pool
        from app.repositories.vectors import DocumentChunkRepository

        pool = await get_pool()
        if pool is None:
            return 0
        repo = DocumentChunkRepository(pool)
        if not repo.enabled:
            return 0
        rows: List[Dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            rows.append(
                {
                    "id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "account_id": chunk.account_id,
                    "domain": domain,
                    "source_type": chunk.source_type,
                    "title": chunk.title,
                    "text": chunk.text,
                    "start_char": chunk.start,
                    "end_char": chunk.end,
                    "embedding": matrix[i].tolist(),
                }
            )
        return await repo.upsert_chunks(rows)
    except Exception:  # noqa: BLE001 - durability is best-effort
        return 0


async def ingest_text(
    *,
    text: str,
    source_type: str = "document",
    title: Optional[str] = None,
    account_id: Optional[str] = None,
    domain: str = "customer_success",
) -> IngestResult:
    """Ingest raw interaction text into the live retrieval corpus.

    This is the single funnel every connector uses. It is fully offline-safe:
    chunking, embedding (hash fallback), and the in-memory index never require a
    network or a database. When a database is configured the chunks are also
    persisted to pgvector for durable semantic retrieval.
    """
    body = (text or "").strip()
    if not body:
        return IngestResult(
            ok=False,
            chunks_written=0,
            source_type=normalize_source_type(source_type),
            domain=domain,
            detail="empty text",
        )

    src = normalize_source_type(source_type)
    clean_title = (title or "").strip() or f"{src.replace('_', ' ').title()} import"
    acct = (account_id or "").strip() or None
    doc_id = _make_doc_id(src)

    # 1) + 2) Chunk and register in the live in-memory corpus (immediately
    # retrievable, citation-exact spans preserved).
    retriever = get_retriever(domain)
    chunks = retriever.add_document(
        doc_id=doc_id,
        account_id=acct,
        source_type=src,
        title=clean_title,
        text=body,
    )
    if not chunks:
        return IngestResult(
            ok=False,
            chunks_written=0,
            doc_id=doc_id,
            account_id=acct,
            source_type=src,
            title=clean_title,
            domain=domain,
            detail="text produced no chunks",
        )

    # 3) Embed (OpenAI when keyed, else deterministic hash embedding).
    matrix, method = await embed_for_index([c.context for c in chunks])

    # 4) Durable persistence to pgvector when available (best-effort).
    written_pg = await _persist_pgvector(domain, chunks, matrix)
    persisted = "pgvector+memory" if written_pg > 0 else "memory"

    return IngestResult(
        ok=True,
        chunks_written=len(chunks),
        ids=[c.chunk_id for c in chunks],
        doc_id=doc_id,
        account_id=acct,
        source_type=src,
        title=clean_title,
        domain=domain,
        embed_method=method,
        persisted=persisted,
        detail=(
            f"Indexed {len(chunks)} chunk(s); "
            + (
                f"persisted {written_pg} to pgvector."
                if written_pg
                else "kept in the in-memory corpus."
            )
        ),
    )


class Connector(ABC):
    """A live ingestion source.

    Implementations adapt a specific input (pasted text, a web query) into one or
    more :class:`IngestResult` records via :func:`ingest_text`. The contract is a
    single async ``ingest`` method so the API layer can treat every source the
    same way.
    """

    #: Stable identifier for the connector (also its default ``source_type``).
    name: str = "connector"

    @abstractmethod
    async def ingest(self, **kwargs: Any) -> IngestResult:
        """Run the connector and return what was written."""
        raise NotImplementedError
