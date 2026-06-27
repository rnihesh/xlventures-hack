"""Async repository for per-org domain pack overrides.

An override lets an org tailor a domain pack's policy rules and action catalog
without forking the base pack. Rows live in the ``pack_overrides`` table, keyed
by ``(org_id, domain)`` with a JSONB ``overrides`` blob shaped like::

    {"policies": [ {...rule...}, ... ], "actions": [ {...action...}, ... ]}

Every method is scoped by ``org_id`` so one org never sees another's edits, and
every method degrades gracefully when no database is configured: a process-local
in-memory store backs the offline path so saving and reading overrides still
round-trip in tests and demos, just not durably.

JSONB is encoded as JSON text and cast with ``::jsonb`` in SQL because the pool
relies on asyncpg's default codecs (which return JSONB as ``str``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from app.deps import get_pool

# Process-local fallback store, keyed by (org_id, domain), for the offline path.
_MEM: Dict[tuple[str, str], Dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _loads(value: Any) -> Dict[str, Any]:
    """Decode a JSONB overrides blob (asyncpg returns it as text) into a dict."""

    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _record(org_id: str, domain: str, overrides: Dict[str, Any], updated_at: str) -> Dict[str, Any]:
    return {
        "org_id": org_id,
        "domain": domain,
        "overrides": overrides,
        "updated_at": updated_at,
    }


async def get(org_id: str, domain: str) -> Optional[Dict[str, Any]]:
    """Return one override row scoped to ``org_id`` / ``domain``, or None."""

    pool = await get_pool()
    if pool is None:
        rec = _MEM.get((org_id, domain))
        return dict(rec) if rec else None

    row = await pool.fetchrow(
        """
        SELECT org_id, domain, overrides, updated_at
        FROM pack_overrides
        WHERE org_id = $1 AND domain = $2
        """,
        org_id,
        domain,
    )
    if row is None:
        return None
    updated = row["updated_at"]
    return _record(
        row["org_id"],
        row["domain"],
        _loads(row["overrides"]),
        updated.isoformat() if hasattr(updated, "isoformat") else str(updated),
    )


async def get_overrides(org_id: str, domain: str) -> Dict[str, Any]:
    """Return just the overrides dict for ``org_id`` / ``domain`` (empty if none).

    Convenience for the loader and policy engine, which only need the merge
    payload and never the row metadata.
    """

    rec = await get(org_id, domain)
    return (rec or {}).get("overrides", {}) or {}


async def upsert(org_id: str, domain: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update the override for ``org_id`` / ``domain`` and return the row."""

    overrides = overrides or {}
    pool = await get_pool()
    if pool is None:
        rec = _record(org_id, domain, dict(overrides), _now())
        _MEM[(org_id, domain)] = rec
        return dict(rec)

    row = await pool.fetchrow(
        """
        INSERT INTO pack_overrides (org_id, domain, overrides, updated_at)
        VALUES ($1, $2, $3::jsonb, now())
        ON CONFLICT (org_id, domain) DO UPDATE SET
            overrides = EXCLUDED.overrides,
            updated_at = now()
        RETURNING org_id, domain, overrides, updated_at
        """,
        org_id,
        domain,
        json.dumps(overrides),
    )
    updated = row["updated_at"]
    return _record(
        row["org_id"],
        row["domain"],
        _loads(row["overrides"]),
        updated.isoformat() if hasattr(updated, "isoformat") else str(updated),
    )


async def delete(org_id: str, domain: str) -> bool:
    """Remove an override (revert to base pack). Returns True if a row was removed."""

    pool = await get_pool()
    if pool is None:
        return _MEM.pop((org_id, domain), None) is not None

    result = await pool.execute(
        "DELETE FROM pack_overrides WHERE org_id = $1 AND domain = $2",
        org_id,
        domain,
    )
    # asyncpg returns a status string like "DELETE 1".
    return result.rsplit(" ", 1)[-1] != "0"
