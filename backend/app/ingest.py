"""Ingest CLI: ``python -m app.ingest``.

Chunks the seed documents, embeds each chunk, and upserts them into the
pgvector ``document_chunks`` table so semantic retrieval is served from Postgres
(cosine distance via ``<=>``). Embeddings use OpenAI when ``OPENAI_API_KEY`` is
set, otherwise a deterministic local hash embedding so the pipeline still runs
fully offline.

When ``DATABASE_URL`` is unset (or ``--dry-run`` is passed) nothing is written:
the corpus is chunked and embedded and a summary of what *would* be written is
printed. Every database dependency is imported lazily so the offline path never
requires asyncpg or a live database.

Usage:
    python -m app.ingest                 # all domains, write if DATABASE_URL set
    python -m app.ingest --domain customer_success
    python -m app.ingest --dry-run       # never write, even if DATABASE_URL set
    python -m app.ingest --json          # machine-readable summary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any, Dict, List

from app.retrieval.chunking import chunk_document
from app.retrieval.embeddings import EMBED_DIM, embed_for_index
from app.retrieval.types import Chunk
from app.seed_data import load_documents

# Keep in sync with app.seed / the domain packs.
DEFAULT_DOMAINS: List[str] = ["customer_success", "collections"]


def _build_chunks(domain: str) -> List[Chunk]:
    """Chunk every seed document for ``domain`` (same path as the retriever)."""
    chunks: List[Chunk] = []
    for doc in load_documents(domain):
        doc_id = doc["id"]
        text = doc.get("text", "") or ""
        chunks.extend(
            chunk_document(
                doc_id=doc_id,
                account_id=doc.get("account_id"),
                source_type=doc.get("source_type", "document"),
                title=doc.get("title", doc_id),
                text=text,
            )
        )
    return chunks


def _rows_for(domain: str, chunks: List[Chunk], matrix: Any) -> List[Dict[str, Any]]:
    """Build upsert row dicts pairing chunks with their embedding vectors."""
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
    return rows


async def run_ingest(domains: List[str], *, dry_run: bool) -> Dict[str, Any]:
    """Chunk, embed, and (optionally) persist every domain corpus."""

    database_url = os.environ.get("DATABASE_URL")
    will_write = bool(database_url) and not dry_run

    pool = None
    repo = None
    if will_write:
        from app.deps import get_pool
        from app.repositories.vectors import DocumentChunkRepository

        pool = await get_pool()
        if pool is None:
            will_write = False
        else:
            repo = DocumentChunkRepository(pool)

    domain_summaries: List[Dict[str, Any]] = []
    try:
        for domain in domains:
            chunks = _build_chunks(domain)
            method = "none"
            written = 0
            if chunks:
                matrix, method = await embed_for_index([c.context for c in chunks])
                if will_write and repo is not None and matrix is not None:
                    rows = _rows_for(domain, chunks, matrix)
                    written = await repo.upsert_chunks(rows)
            domain_summaries.append(
                {
                    "domain": domain,
                    "chunks": len(chunks),
                    "embed_method": method,
                    "written": written,
                }
            )
    finally:
        if will_write:
            from app.deps import close_pool

            await close_pool()

    return {
        "mode": "write" if will_write else "validate",
        "database_configured": bool(database_url),
        "dry_run": dry_run,
        "embedding_dim": EMBED_DIM,
        "domains": domain_summaries,
    }


def _print_summary(payload: Dict[str, Any]) -> None:
    mode = payload["mode"]
    header = (
        "Ingest (write embeddings to pgvector)"
        if mode == "write"
        else "Ingest (offline, no write)"
    )
    print(header)
    print("=" * 64)
    print(f"Embedding dimension: {payload['embedding_dim']}")

    total_chunks = 0
    total_written = 0
    for d in payload["domains"]:
        total_chunks += d["chunks"]
        total_written += d["written"]
        line = (
            f"  {d['domain']:<20} chunks={d['chunks']:<4} "
            f"embed={d['embed_method']:<7}"
        )
        if d["written"]:
            line += f" -> wrote {d['written']}"
        print(line)

    print("-" * 64)
    print(f"Totals: chunks={total_chunks} written={total_written}")
    if mode != "write":
        if payload["dry_run"]:
            print("Dry run: no rows written.")
        elif not payload["database_configured"]:
            print("No DATABASE_URL: nothing written (chunked + embedded only).")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.ingest",
        description="Chunk, embed, and persist seed documents into pgvector.",
    )
    parser.add_argument(
        "--domain",
        action="append",
        dest="domains",
        help="Limit to a domain (repeatable). Defaults to all known domains.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chunk and embed only; never write, even if DATABASE_URL is set.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the summary as JSON instead of a human-readable table.",
    )
    args = parser.parse_args(argv)

    domains = args.domains or DEFAULT_DOMAINS
    payload = asyncio.run(run_ingest(domains, dry_run=args.dry_run))

    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        _print_summary(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
