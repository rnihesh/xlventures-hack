"""Async repository for run records.

Wraps an asyncpg pool to persist and query the ``runs`` table. Every method is
a graceful no-op (returns ``None`` / empty) when the pool is ``None`` so the app
runs identically offline (no DATABASE_URL) and online.

JSONB columns are encoded as JSON text and cast with ``::jsonb`` in SQL because
the pool relies on asyncpg's default codecs (which return JSONB as ``str``).
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
    """Convert a run record to a plain dict, decoding JSONB columns."""
    data = dict(row)
    for key in ("signal", "payload"):
        if key in data:
            data[key] = _loads(data[key])
    return data


class RunsRepository:
    """Persist and query rows in the ``runs`` table."""

    def __init__(self, pool: Optional[asyncpg.Pool]) -> None:
        self._pool = pool

    @property
    def enabled(self) -> bool:
        """True when a pool is available (online / persistent mode)."""
        return self._pool is not None

    async def create(
        self,
        run_id: str,
        domain: str,
        account_id: str,
        signal: Optional[Dict[str, Any]] = None,
        status: str = "created",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Insert a run; returns its id, or None when persistence is disabled."""
        if self._pool is None:
            return None
        await self._pool.execute(
            """
            INSERT INTO runs (id, domain, account_id, signal, status, payload)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                domain = EXCLUDED.domain,
                account_id = EXCLUDED.account_id,
                signal = EXCLUDED.signal,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = now()
            """,
            run_id,
            domain,
            account_id,
            _dumps(signal),
            status,
            _dumps(payload),
        )
        return run_id

    async def update_status(
        self, run_id: str, status: str, payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update a run's status (and optionally its payload)."""
        if self._pool is None:
            return
        if payload is None:
            await self._pool.execute(
                "UPDATE runs SET status = $2, updated_at = now() WHERE id = $1",
                run_id,
                status,
            )
        else:
            await self._pool.execute(
                """
                UPDATE runs
                SET status = $2, payload = $3::jsonb, updated_at = now()
                WHERE id = $1
                """,
                run_id,
                status,
                _dumps(payload),
            )

    async def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return a run by id, or None when missing / disabled."""
        if self._pool is None:
            return None
        row = await self._pool.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
        return _row_to_dict(row) if row else None

    async def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent runs (newest first); empty when disabled."""
        if self._pool is None:
            return []
        rows = await self._pool.fetch(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT $1", limit
        )
        return [_row_to_dict(r) for r in rows]
