"""Async repository for per-org integration connectors.

Connectors live in the ``org_connectors`` table, keyed by ``(org_id, kind)``
with a JSONB ``config`` blob and a short ``status`` label. Every method is
scoped by ``org_id`` so one org never sees another's connectors, and every
method degrades gracefully when no database is configured: a process-local
in-memory store backs the offline path so saving and listing connectors still
round-trip in tests and demos, just not durably.

JSONB is encoded as JSON text and cast with ``::jsonb`` in SQL because the pool
relies on asyncpg's default codecs (which return JSONB as ``str``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from app.deps import get_pool

# Channel kinds the platform knows how to configure and send through.
KINDS = ("ses", "slack", "google")

# Process-local fallback store, keyed by (org_id, kind), for the offline path.
_MEM: Dict[tuple[str, str], Dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _loads(value: Any) -> Dict[str, Any]:
    """Decode a JSONB config (asyncpg returns it as text) into a dict."""

    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _record(org_id: str, kind: str, config: Dict[str, Any], status: str, updated_at: str) -> Dict[str, Any]:
    return {
        "org_id": org_id,
        "kind": kind,
        "config": config,
        "status": status,
        "updated_at": updated_at,
    }


async def get(org_id: str, kind: str) -> Optional[Dict[str, Any]]:
    """Return one connector scoped to ``org_id`` / ``kind``, or None when absent."""

    pool = await get_pool()
    if pool is None:
        rec = _MEM.get((org_id, kind))
        return dict(rec) if rec else None

    row = await pool.fetchrow(
        """
        SELECT org_id, kind, config, status, updated_at
        FROM org_connectors
        WHERE org_id = $1 AND kind = $2
        """,
        org_id,
        kind,
    )
    if row is None:
        return None
    updated = row["updated_at"]
    return _record(
        row["org_id"],
        row["kind"],
        _loads(row["config"]),
        row["status"],
        updated.isoformat() if hasattr(updated, "isoformat") else str(updated),
    )


async def upsert(
    org_id: str,
    kind: str,
    config: Dict[str, Any],
    status: str = "connected",
) -> Dict[str, Any]:
    """Insert or update a connector under ``org_id`` and return it."""

    config = config or {}
    pool = await get_pool()
    if pool is None:
        rec = _record(org_id, kind, dict(config), status, _now())
        _MEM[(org_id, kind)] = rec
        return dict(rec)

    row = await pool.fetchrow(
        """
        INSERT INTO org_connectors (org_id, kind, config, status, updated_at)
        VALUES ($1, $2, $3::jsonb, $4, now())
        ON CONFLICT (org_id, kind) DO UPDATE SET
            config = EXCLUDED.config,
            status = EXCLUDED.status,
            updated_at = now()
        RETURNING org_id, kind, config, status, updated_at
        """,
        org_id,
        kind,
        json.dumps(config),
        status,
    )
    updated = row["updated_at"]
    return _record(
        row["org_id"],
        row["kind"],
        _loads(row["config"]),
        row["status"],
        updated.isoformat() if hasattr(updated, "isoformat") else str(updated),
    )


async def delete(org_id: str, kind: str) -> bool:
    """Remove a connector scoped to ``org_id`` / ``kind``. Returns True if removed."""

    pool = await get_pool()
    if pool is None:
        return _MEM.pop((org_id, kind), None) is not None

    result = await pool.execute(
        "DELETE FROM org_connectors WHERE org_id = $1 AND kind = $2",
        org_id,
        kind,
    )
    # asyncpg returns a status string like "DELETE 1".
    return result.rsplit(" ", 1)[-1] != "0"


async def list(org_id: str) -> List[Dict[str, Any]]:
    """Return every connector configured for ``org_id``, ordered by kind."""

    pool = await get_pool()
    if pool is None:
        rows = [dict(rec) for (oid, _k), rec in _MEM.items() if oid == org_id]
        return sorted(rows, key=lambda r: r["kind"])

    records = await pool.fetch(
        """
        SELECT org_id, kind, config, status, updated_at
        FROM org_connectors
        WHERE org_id = $1
        ORDER BY kind
        """,
        org_id,
    )
    out: List[Dict[str, Any]] = []
    for row in records:
        updated = row["updated_at"]
        out.append(
            _record(
                row["org_id"],
                row["kind"],
                _loads(row["config"]),
                row["status"],
                updated.isoformat() if hasattr(updated, "isoformat") else str(updated),
            )
        )
    return out
