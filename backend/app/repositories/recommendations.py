"""Async repository for recommendation records.

Wraps an asyncpg pool to persist and query the ``recommendations`` table. Every
method is a graceful no-op (returns ``None`` / empty) when the pool is ``None``
so the app runs identically offline and online.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import asyncpg


def _dumps(value: Any) -> Optional[str]:
    """Serialize a JSON-able value to text, or None when value is None."""
    if value is None:
        return None
    return json.dumps(value)


def _loads(value: Any) -> Any:
    """Decode a JSONB column (asyncpg returns it as text) back into Python."""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _row_to_dict(row: asyncpg.Record) -> Dict[str, Any]:
    """Convert a recommendation record to a dict, decoding the JSONB payload."""
    data = dict(row)
    if "payload" in data:
        data["payload"] = _loads(data["payload"])
    return data


class RecommendationsRepository:
    """Persist and query rows in the ``recommendations`` table."""

    def __init__(self, pool: Optional[asyncpg.Pool]) -> None:
        self._pool = pool

    @property
    def enabled(self) -> bool:
        """True when a pool is available (online / persistent mode)."""
        return self._pool is not None

    async def create(
        self,
        rec_id: str,
        run_id: str,
        account_id: str,
        domain: str,
        payload: Dict[str, Any],
        status: str = "proposed",
    ) -> Optional[str]:
        """Insert (or upsert) a recommendation; returns its id, or None offline."""
        if self._pool is None:
            return None
        await self._pool.execute(
            """
            INSERT INTO recommendations
                (id, run_id, account_id, domain, payload, status)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            ON CONFLICT (id) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                account_id = EXCLUDED.account_id,
                domain = EXCLUDED.domain,
                payload = EXCLUDED.payload,
                status = EXCLUDED.status,
                updated_at = now()
            """,
            rec_id,
            run_id,
            account_id,
            domain,
            _dumps(payload),
            status,
        )
        return rec_id

    async def update_status(
        self, rec_id: str, status: str, payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update a recommendation's status (and optionally its payload)."""
        if self._pool is None:
            return
        if payload is None:
            await self._pool.execute(
                "UPDATE recommendations SET status = $2, updated_at = now() WHERE id = $1",
                rec_id,
                status,
            )
        else:
            await self._pool.execute(
                """
                UPDATE recommendations
                SET status = $2, payload = $3::jsonb, updated_at = now()
                WHERE id = $1
                """,
                rec_id,
                status,
                _dumps(payload),
            )

    async def get(self, rec_id: str) -> Optional[Dict[str, Any]]:
        """Return a recommendation by id, or None when missing / disabled."""
        if self._pool is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT * FROM recommendations WHERE id = $1", rec_id
        )
        return _row_to_dict(row) if row else None

    async def list_for_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Return recommendations for a run (newest first); empty when disabled."""
        if self._pool is None:
            return []
        rows = await self._pool.fetch(
            "SELECT * FROM recommendations WHERE run_id = $1 ORDER BY created_at DESC",
            run_id,
        )
        return [_row_to_dict(r) for r in rows]
