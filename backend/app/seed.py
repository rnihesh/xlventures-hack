"""Seed CLI: ``python -m app.seed``.

Loads the seed corpora (accounts, documents, and day-zero episodes) for every
configured domain and reports a summary. When ``DATABASE_URL`` is set it
writes the corpora into Postgres through a small, idempotent persistence layer;
otherwise it runs fully offline, validating the data and printing what *would*
be written. Every database dependency is imported lazily so the offline path
never requires asyncpg, a pool, or a live database.

Usage:
    python -m app.seed                # all domains, write if DATABASE_URL set
    python -m app.seed --domain collections
    python -m app.seed --dry-run      # never write, even if DATABASE_URL set
    python -m app.seed --json         # machine-readable summary

This module owns no schema migrations; it creates its seed tables defensively
with ``CREATE TABLE IF NOT EXISTS`` so it is safe to run repeatedly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any, Dict, List

# Domains whose corpora live under ``backend/seeds/<domain>/``. Keep this in
# sync with the domain packs under ``domain_packs/``.
DEFAULT_DOMAINS: List[str] = ["customer_success", "collections"]


# ---------------------------------------------------------------------------
# Loading (offline, no DB)
# ---------------------------------------------------------------------------
def _load_corpus(domain: str) -> Dict[str, Any]:
    """Load accounts, documents, and episodes for one domain.

    Imports are local so importing this module is cheap and side-effect free.
    """

    from app.seed_data import load_accounts, load_documents

    accounts = load_accounts(domain)
    documents = load_documents(domain)

    # Episodes are only seeded for the flagship domain today; other domains
    # simply have none, which is fine.
    episodes: List[Dict[str, Any]] = []
    try:
        from app.memory.seed_episodes import load_seed_episodes

        episodes = [
            ep.public()
            for ep in load_seed_episodes()
            if getattr(ep, "domain", None) == domain
        ]
    except Exception:  # noqa: BLE001 - episodes are optional for seeding
        episodes = []

    return {
        "domain": domain,
        "accounts": accounts,
        "documents": documents,
        "episodes": episodes,
    }


def _validate_corpus(corpus: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable validation warnings (empty == clean)."""

    warnings: List[str] = []
    domain = corpus["domain"]

    seen_accounts: set[str] = set()
    for i, acc in enumerate(corpus["accounts"]):
        acc_id = acc.get("account_id")
        if not acc_id:
            warnings.append(f"{domain}: account #{i} is missing 'account_id'")
            continue
        if acc_id in seen_accounts:
            warnings.append(f"{domain}: duplicate account_id '{acc_id}'")
        seen_accounts.add(acc_id)

    seen_docs: set[str] = set()
    for i, doc in enumerate(corpus["documents"]):
        doc_id = doc.get("id")
        if not doc_id:
            warnings.append(f"{domain}: document #{i} is missing 'id'")
            continue
        if doc_id in seen_docs:
            warnings.append(f"{domain}: duplicate document id '{doc_id}'")
        seen_docs.add(doc_id)
        if not (doc.get("text") or "").strip():
            warnings.append(f"{domain}: document '{doc_id}' has empty text")
        # Account-scoped documents should reference a known account.
        ref = doc.get("account_id")
        if ref and ref not in seen_accounts:
            warnings.append(
                f"{domain}: document '{doc_id}' references unknown account '{ref}'"
            )

    return warnings


# ---------------------------------------------------------------------------
# Persistence (only touched when DATABASE_URL is set and not a dry run)
# ---------------------------------------------------------------------------
_DDL = (
    """
    CREATE TABLE IF NOT EXISTS seed_accounts (
        account_id TEXT PRIMARY KEY,
        domain     TEXT NOT NULL,
        name       TEXT,
        data       JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS seed_documents (
        id         TEXT PRIMARY KEY,
        domain     TEXT NOT NULL,
        account_id TEXT,
        source_type TEXT,
        title      TEXT,
        text       TEXT,
        data       JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS seed_episodes (
        id         TEXT PRIMARY KEY,
        domain     TEXT NOT NULL,
        account_id TEXT,
        data       JSONB NOT NULL
    )
    """,
)


async def _write_corpus(pool: Any, corpus: Dict[str, Any]) -> Dict[str, int]:
    """Upsert one domain's corpus through an asyncpg pool. Idempotent."""

    domain = corpus["domain"]
    counts = {"accounts": 0, "documents": 0, "episodes": 0}

    async with pool.acquire() as conn:
        for stmt in _DDL:
            await conn.execute(stmt)

        for acc in corpus["accounts"]:
            await conn.execute(
                """
                INSERT INTO seed_accounts (account_id, domain, name, data)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (account_id) DO UPDATE
                    SET domain = EXCLUDED.domain,
                        name   = EXCLUDED.name,
                        data   = EXCLUDED.data
                """,
                acc.get("account_id"),
                domain,
                acc.get("name"),
                json.dumps(acc),
            )
            counts["accounts"] += 1

        for doc in corpus["documents"]:
            await conn.execute(
                """
                INSERT INTO seed_documents
                    (id, domain, account_id, source_type, title, text, data)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE
                    SET domain      = EXCLUDED.domain,
                        account_id  = EXCLUDED.account_id,
                        source_type = EXCLUDED.source_type,
                        title       = EXCLUDED.title,
                        text        = EXCLUDED.text,
                        data        = EXCLUDED.data
                """,
                doc.get("id"),
                domain,
                doc.get("account_id"),
                doc.get("source_type"),
                doc.get("title"),
                doc.get("text"),
                json.dumps(doc),
            )
            counts["documents"] += 1

        for ep in corpus["episodes"]:
            await conn.execute(
                """
                INSERT INTO seed_episodes (id, domain, account_id, data)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (id) DO UPDATE
                    SET domain     = EXCLUDED.domain,
                        account_id = EXCLUDED.account_id,
                        data       = EXCLUDED.data
                """,
                ep.get("id"),
                domain,
                ep.get("account_id"),
                json.dumps(ep),
            )
            counts["episodes"] += 1

    return counts


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
async def run_seed(domains: List[str], *, dry_run: bool) -> Dict[str, Any]:
    """Load (and optionally write) every domain corpus; return a summary dict."""

    database_url = os.environ.get("DATABASE_URL")
    will_write = bool(database_url) and not dry_run

    pool = None
    if will_write:
        # Lazy import so the offline path has no asyncpg/database dependency.
        from app.deps import get_pool

        pool = await get_pool()
        if pool is None:
            will_write = False

    domain_summaries: List[Dict[str, Any]] = []
    all_warnings: List[str] = []
    try:
        for domain in domains:
            corpus = _load_corpus(domain)
            warnings = _validate_corpus(corpus)
            all_warnings.extend(warnings)

            written = None
            if will_write and pool is not None:
                written = await _write_corpus(pool, corpus)

            domain_summaries.append(
                {
                    "domain": domain,
                    "accounts": len(corpus["accounts"]),
                    "documents": len(corpus["documents"]),
                    "episodes": len(corpus["episodes"]),
                    "warnings": warnings,
                    "written": written,
                }
            )
    finally:
        if will_write:
            # Close the pool we opened so the CLI exits cleanly.
            from app.deps import close_pool

            await close_pool()

    return {
        "mode": "write" if will_write else "validate",
        "database_configured": bool(database_url),
        "dry_run": dry_run,
        "domains": domain_summaries,
        "warnings": all_warnings,
    }


def _print_summary(payload: Dict[str, Any]) -> None:
    mode = payload["mode"]
    header = (
        "Seeding (write to Postgres)"
        if mode == "write"
        else "Seeding (offline validate, no DATABASE_URL)"
    )
    print(header)
    print("=" * 64)

    totals = {"accounts": 0, "documents": 0, "episodes": 0}
    for d in payload["domains"]:
        totals["accounts"] += d["accounts"]
        totals["documents"] += d["documents"]
        totals["episodes"] += d["episodes"]
        flag = "WARN" if d["warnings"] else "OK"
        line = (
            f"[{flag}] {d['domain']:<20} "
            f"accounts={d['accounts']:<3} documents={d['documents']:<3} "
            f"episodes={d['episodes']:<3}"
        )
        if d["written"]:
            w = d["written"]
            line += (
                f"  -> wrote a={w['accounts']} d={w['documents']} e={w['episodes']}"
            )
        print(line)
        for warning in d["warnings"]:
            print(f"       - {warning}")

    print("-" * 64)
    print(
        f"Totals: accounts={totals['accounts']} "
        f"documents={totals['documents']} episodes={totals['episodes']}"
    )
    if payload["warnings"]:
        print(f"Validation warnings: {len(payload['warnings'])}")
    else:
        print("Validation: clean")
    if mode != "write":
        if payload["dry_run"]:
            print("Dry run: no rows written.")
        elif not payload["database_configured"]:
            print("No DATABASE_URL: nothing written (offline validation only).")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.seed",
        description="Load and (optionally) persist the seed corpora.",
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
        help="Validate and summarize only; never write, even if DATABASE_URL is set.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the summary as JSON instead of a human-readable table.",
    )
    args = parser.parse_args(argv)

    domains = args.domains or DEFAULT_DOMAINS
    payload = asyncio.run(run_seed(domains, dry_run=args.dry_run))

    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        _print_summary(payload)

    # Non-zero exit only on validation warnings, so CI can gate on clean seeds.
    return 1 if payload["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
