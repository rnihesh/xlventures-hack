"""Async repository for per-org uploaded domain packs.

An org pack is a whole new domain an org authored at runtime by uploading a YAML
pack (the "add a domain in 60 seconds" flow). Unlike ``pack_overrides`` (which
tailors an existing base pack), this stores a brand new vertical: the raw YAML
the org wrote, plus a validated ``parsed`` blob cached so reads never re-parse.
Rows live in the ``org_packs`` table, keyed by ``(org_id, domain)``.

Every method is scoped by ``org_id`` so one org never sees another org's uploaded
packs, and every method degrades gracefully when no database is configured: a
process-local in-memory store backs the offline path so saving and reading packs
still round-trip in tests and demos, just not durably.

On every successful upsert (and delete) the loader's in-process org pack registry
is updated so a RUN on the new domain immediately resolves the uploaded pack,
without re-reading the database from inside the synchronous graph.

JSONB is encoded as JSON text and cast with ``::jsonb`` in SQL because the pool
relies on asyncpg's default codecs (which return JSONB as ``str``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import yaml

from app.deps import get_pool
from app.packs import loader as pack_loader
from app.packs.schema import DomainPack, PackValidationError, validate_pack

# Process-local fallback store, keyed by (org_id, domain), for the offline path.
_MEM: Dict[tuple[str, str], Dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _loads(value: Any) -> Dict[str, Any]:
    """Decode a JSONB parsed blob (asyncpg returns it as text) into a dict."""

    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _record(
    org_id: str,
    domain: str,
    name: str,
    yaml_text: str,
    parsed: Dict[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    return {
        "org_id": org_id,
        "domain": domain,
        "name": name,
        "yaml": yaml_text,
        "parsed": parsed,
        "created_at": created_at,
    }


def _parse_yaml(yaml_text: str) -> Any:
    """Safely load YAML text into plain data. Never executes arbitrary code."""

    try:
        return yaml.safe_load(yaml_text or "")
    except yaml.YAMLError as exc:  # noqa: BLE001 - surface as a validation error.
        raise PackValidationError([f"YAML parse error: {exc}".replace("\n", " ")]) from exc


def validate_yaml(yaml_text: str) -> DomainPack:
    """Parse and validate raw YAML into a DomainPack or raise PackValidationError."""

    return validate_pack(_parse_yaml(yaml_text))


async def list_for_org(org_id: str) -> List[Dict[str, Any]]:
    """Return every uploaded pack row for ``org_id`` (empty list if none)."""

    pool = await get_pool()
    if pool is None:
        rows = [dict(rec) for (oid, _dom), rec in _MEM.items() if oid == org_id]
        rows.sort(key=lambda r: r.get("domain", ""))
        return rows

    records = await pool.fetch(
        """
        SELECT org_id, domain, name, yaml, parsed, created_at
        FROM org_packs
        WHERE org_id = $1
        ORDER BY domain
        """,
        org_id,
    )
    out: List[Dict[str, Any]] = []
    for row in records:
        created = row["created_at"]
        out.append(
            _record(
                row["org_id"],
                row["domain"],
                row["name"] or "",
                row["yaml"] or "",
                _loads(row["parsed"]),
                created.isoformat() if hasattr(created, "isoformat") else str(created),
            )
        )
    return out


async def get(org_id: str, domain: str) -> Optional[Dict[str, Any]]:
    """Return one uploaded pack row scoped to ``org_id`` / ``domain``, or None."""

    pool = await get_pool()
    if pool is None:
        rec = _MEM.get((org_id, domain))
        return dict(rec) if rec else None

    row = await pool.fetchrow(
        """
        SELECT org_id, domain, name, yaml, parsed, created_at
        FROM org_packs
        WHERE org_id = $1 AND domain = $2
        """,
        org_id,
        domain,
    )
    if row is None:
        return None
    created = row["created_at"]
    return _record(
        row["org_id"],
        row["domain"],
        row["name"] or "",
        row["yaml"] or "",
        _loads(row["parsed"]),
        created.isoformat() if hasattr(created, "isoformat") else str(created),
    )


async def upsert(org_id: str, yaml_text: str) -> Dict[str, Any]:
    """Validate ``yaml_text``, store it as an org pack, and return the row.

    The domain key is taken from the validated pack, so the caller does not pass
    it separately. Raises ``PackValidationError`` when the YAML is invalid, so an
    org can never store a pack that would not run. Registers the parsed pack with
    the loader so a RUN on the new domain resolves it immediately.
    """

    pack = validate_yaml(yaml_text)
    domain = pack.domain
    name = pack.display_name or domain
    parsed = pack.model_dump()

    pool = await get_pool()
    if pool is None:
        rec = _record(org_id, domain, name, yaml_text, parsed, _now())
        _MEM[(org_id, domain)] = rec
        pack_loader.register_org_pack(org_id, domain, parsed)
        return dict(rec)

    row = await pool.fetchrow(
        """
        INSERT INTO org_packs (org_id, domain, name, yaml, parsed, created_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, now())
        ON CONFLICT (org_id, domain) DO UPDATE SET
            name = EXCLUDED.name,
            yaml = EXCLUDED.yaml,
            parsed = EXCLUDED.parsed
        RETURNING org_id, domain, name, yaml, parsed, created_at
        """,
        org_id,
        domain,
        name,
        yaml_text,
        json.dumps(parsed),
    )
    created = row["created_at"]
    pack_loader.register_org_pack(org_id, domain, parsed)
    return _record(
        row["org_id"],
        row["domain"],
        row["name"] or "",
        row["yaml"] or "",
        _loads(row["parsed"]),
        created.isoformat() if hasattr(created, "isoformat") else str(created),
    )


async def delete(org_id: str, domain: str) -> bool:
    """Remove an uploaded org pack. Returns True if a row was removed."""

    pack_loader.unregister_org_pack(org_id, domain)

    pool = await get_pool()
    if pool is None:
        return _MEM.pop((org_id, domain), None) is not None

    result = await pool.execute(
        "DELETE FROM org_packs WHERE org_id = $1 AND domain = $2",
        org_id,
        domain,
    )
    # asyncpg returns a status string like "DELETE 1".
    return result.rsplit(" ", 1)[-1] != "0"


async def hydrate_loader(org_id: str) -> None:
    """Register every stored pack for ``org_id`` into the loader registry.

    Called on demand (for example when a run is about to start) so a fresh
    process that lost its in-memory registry can still resolve a previously
    uploaded pack from durable storage.
    """

    for rec in await list_for_org(org_id):
        parsed = rec.get("parsed") or {}
        if parsed:
            pack_loader.register_org_pack(org_id, rec["domain"], parsed)
