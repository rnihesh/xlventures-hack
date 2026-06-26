"""Seed the Demo org's data into the multi-tenant tables.

Loads every ``backend/seeds/<domain>/accounts.json`` record and upserts it into
the ``accounts`` table under ``org_id='org_demo'`` (the org that owns all seed
data), and re-tags any existing ``document_chunks`` rows to the demo org so the
seeded knowledge base is scoped to it. Both steps are idempotent, so this is
safe to run repeatedly.

Run as a one-off after migrations:

    python -m app.seed_orgs

It is a no-op (with a clear message) when no database is configured, since the
API falls back to the in-memory seed corpus offline.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.repositories.accounts_repo import AccountsRepository
from app.seed_data import load_accounts

DEMO_ORG = "org_demo"

# Domains whose seed accounts belong to the demo org.
_DOMAINS = ["customer_success", "saas_sales", "collections"]


async def seed_demo_org(pool: Any) -> Dict[str, int]:
    """Upsert demo accounts and re-tag demo document chunks.

    Returns a small summary of what was written. A ``None`` pool yields a
    zeroed summary so callers can run it unconditionally.
    """
    summary = {"accounts": 0, "chunks_retagged": 0}
    if pool is None:
        return summary

    repo = AccountsRepository(pool)
    for domain in _DOMAINS:
        accounts: List[Dict[str, Any]] = load_accounts(domain)
        for account in accounts:
            account_id = account.get("account_id")
            if not account_id:
                continue
            payload = {k: v for k, v in account.items() if k != "account_id"}
            payload.setdefault("domain", domain)
            await repo.upsert(DEMO_ORG, account_id, domain, payload)
            summary["accounts"] += 1

    # Re-tag any pre-existing document chunks (seeded knowledge) to the demo org.
    try:
        result = await pool.execute(
            "UPDATE document_chunks SET org_id = $1 WHERE org_id IS NULL",
            DEMO_ORG,
        )
        # asyncpg returns a status string like "UPDATE 42".
        summary["chunks_retagged"] = int(str(result).split()[-1]) if result else 0
    except Exception:  # noqa: BLE001 - retag is best-effort (table may be empty)
        pass

    return summary


async def _run() -> Dict[str, int]:
    """Acquire the pool, seed, and close it (CLI entry helper)."""
    from app.deps import close_pool, get_pool

    pool = await get_pool()
    if pool is None:
        print("No DATABASE_URL configured: nothing to seed (offline demo mode).")
        return {"accounts": 0, "chunks_retagged": 0}
    try:
        summary = await seed_demo_org(pool)
    finally:
        await close_pool()
    print(
        f"Seeded demo org: {summary['accounts']} accounts, "
        f"{summary['chunks_retagged']} document chunks re-tagged."
    )
    return summary


def main() -> int:
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
