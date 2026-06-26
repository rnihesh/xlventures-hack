"""Async repository for org-scoped domain accounts.

Accounts live in the ``accounts`` table, keyed by ``(org_id, account_id)`` with
the full account record stored as a JSONB ``payload``. Every method is scoped by
``org_id`` so one org never sees another's accounts, and every method is a
graceful no-op (returns empty / None) when the pool is ``None`` so the app runs
identically offline (no DATABASE_URL), where the API layer falls back to the
seeded demo corpus.

JSONB is encoded as JSON text and cast with ``::jsonb`` in SQL because the pool
relies on asyncpg's default codecs (which return JSONB as ``str``).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import asyncpg


def _loads(value: Any) -> Dict[str, Any]:
    """Decode a JSONB payload (asyncpg returns it as text) into a dict."""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _row_to_account(row: asyncpg.Record) -> Dict[str, Any]:
    """Project a row onto the account record, merging payload + key columns."""
    payload = _loads(row["payload"])
    account = dict(payload)
    # The columns are authoritative for identity / domain.
    account["account_id"] = row["account_id"]
    account.setdefault("domain", row["domain"])
    account["domain"] = row["domain"]
    return account


class AccountsRepository:
    """Persist and query org-scoped accounts in the ``accounts`` table."""

    def __init__(self, pool: Optional[asyncpg.Pool]) -> None:
        self._pool = pool

    @property
    def enabled(self) -> bool:
        """True when a pool is available (database-backed accounts)."""
        return self._pool is not None

    async def list_for_org(
        self, org_id: str, domain: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return every account for ``org_id`` (optionally scoped to ``domain``)."""
        if self._pool is None:
            return []
        if domain is None:
            rows = await self._pool.fetch(
                """
                SELECT org_id, account_id, domain, payload
                FROM accounts
                WHERE org_id = $1
                ORDER BY account_id
                """,
                org_id,
            )
        else:
            rows = await self._pool.fetch(
                """
                SELECT org_id, account_id, domain, payload
                FROM accounts
                WHERE org_id = $1 AND domain = $2
                ORDER BY account_id
                """,
                org_id,
                domain,
            )
        return [_row_to_account(r) for r in rows]

    async def get(self, org_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        """Return one account scoped to ``org_id``, or None when absent."""
        if self._pool is None:
            return None
        row = await self._pool.fetchrow(
            """
            SELECT org_id, account_id, domain, payload
            FROM accounts
            WHERE org_id = $1 AND account_id = $2
            """,
            org_id,
            account_id,
        )
        return _row_to_account(row) if row else None

    async def upsert(
        self,
        org_id: str,
        account_id: str,
        domain: str,
        payload: Dict[str, Any],
    ) -> Optional[str]:
        """Upsert an account under ``org_id``; returns its id, or None offline."""
        if self._pool is None:
            return None
        await self._pool.execute(
            """
            INSERT INTO accounts (org_id, account_id, domain, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (org_id, account_id) DO UPDATE SET
                domain = EXCLUDED.domain,
                payload = EXCLUDED.payload
            """,
            org_id,
            account_id,
            domain,
            json.dumps(payload or {}),
        )
        return account_id
