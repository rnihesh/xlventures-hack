"""Async repository for org-scoped contacts.

Contacts live in the ``contacts`` table, one row per contact keyed by ``id``
and always scoped by ``org_id`` so one org never sees another's people. A
contact carries a ``name``, an ``email``, an optional linked ``account_id``, and
a free-text ``role``.

Every method degrades gracefully when no database is configured: a process-local
in-memory store backs the offline path so creating, listing, resolving, and
deleting contacts still round-trip in tests and demos, just not durably. This
mirrors the connectors / accounts repositories so the whole data layer behaves
identically online and offline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from app.deps import get_pool

# Process-local fallback store, keyed by org_id then contact id, for offline use.
_MEM: Dict[str, Dict[str, Dict[str, Any]]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    """Return a stable, readable contact id (e.g. ``con_9f3a2b1c``)."""

    return f"con_{uuid.uuid4().hex[:8]}"


def _record(
    contact_id: str,
    org_id: str,
    name: str,
    email: str,
    account_id: Optional[str],
    role: Optional[str],
    created_at: str,
) -> Dict[str, Any]:
    return {
        "id": contact_id,
        "org_id": org_id,
        "name": name,
        "email": email,
        "account_id": account_id,
        "role": role,
        "created_at": created_at,
    }


def _row_to_contact(row: Any) -> Dict[str, Any]:
    created = row["created_at"]
    return _record(
        row["id"],
        row["org_id"],
        row["name"],
        row["email"],
        row["account_id"],
        row["role"],
        created.isoformat() if hasattr(created, "isoformat") else str(created),
    )


async def list_for_org(org_id: str) -> List[Dict[str, Any]]:
    """Return every contact for ``org_id``, most recent first."""

    pool = await get_pool()
    if pool is None:
        rows = list(_MEM.get(org_id, {}).values())
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)

    records = await pool.fetch(
        """
        SELECT id, org_id, name, email, account_id, role, created_at
        FROM contacts
        WHERE org_id = $1
        ORDER BY created_at DESC
        """,
        org_id,
    )
    return [_row_to_contact(r) for r in records]


async def list_for_account(org_id: str, account_id: str) -> List[Dict[str, Any]]:
    """Return the org's contacts linked to one account, most recent first."""

    pool = await get_pool()
    if pool is None:
        rows = [
            r
            for r in _MEM.get(org_id, {}).values()
            if r.get("account_id") == account_id
        ]
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)

    records = await pool.fetch(
        """
        SELECT id, org_id, name, email, account_id, role, created_at
        FROM contacts
        WHERE org_id = $1 AND account_id = $2
        ORDER BY created_at DESC
        """,
        org_id,
        account_id,
    )
    return [_row_to_contact(r) for r in records]


async def get(org_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """Return one contact scoped to ``org_id``, or None when absent."""

    pool = await get_pool()
    if pool is None:
        rec = _MEM.get(org_id, {}).get(contact_id)
        return dict(rec) if rec else None

    row = await pool.fetchrow(
        """
        SELECT id, org_id, name, email, account_id, role, created_at
        FROM contacts
        WHERE org_id = $1 AND id = $2
        """,
        org_id,
        contact_id,
    )
    return _row_to_contact(row) if row else None


async def upsert(
    org_id: str,
    name: str,
    email: str,
    account_id: Optional[str] = None,
    role: Optional[str] = None,
    contact_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a new contact, or update an existing one when ``contact_id`` is given."""

    pool = await get_pool()
    if pool is None:
        org_mem = _MEM.setdefault(org_id, {})
        existing = org_mem.get(contact_id) if contact_id else None
        cid = contact_id or _new_id()
        created = existing.get("created_at") if existing else _now()
        rec = _record(cid, org_id, name, email, account_id, role, created)
        org_mem[cid] = rec
        return dict(rec)

    if contact_id:
        row = await pool.fetchrow(
            """
            INSERT INTO contacts (id, org_id, name, email, account_id, role)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                email = EXCLUDED.email,
                account_id = EXCLUDED.account_id,
                role = EXCLUDED.role
            RETURNING id, org_id, name, email, account_id, role, created_at
            """,
            contact_id,
            org_id,
            name,
            email,
            account_id,
            role,
        )
    else:
        row = await pool.fetchrow(
            """
            INSERT INTO contacts (id, org_id, name, email, account_id, role)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, org_id, name, email, account_id, role, created_at
            """,
            _new_id(),
            org_id,
            name,
            email,
            account_id,
            role,
        )
    return _row_to_contact(row)


async def delete(org_id: str, contact_id: str) -> bool:
    """Remove a contact scoped to ``org_id`` / ``contact_id``. True if removed."""

    pool = await get_pool()
    if pool is None:
        org_mem = _MEM.get(org_id, {})
        return org_mem.pop(contact_id, None) is not None

    result = await pool.execute(
        "DELETE FROM contacts WHERE org_id = $1 AND id = $2",
        org_id,
        contact_id,
    )
    # asyncpg returns a status string like "DELETE 1".
    return result.rsplit(" ", 1)[-1] != "0"


async def find_by_name_or_email(
    org_id: str, query: str
) -> Optional[Dict[str, Any]]:
    """Resolve a contact within ``org_id`` by exact email or (fuzzy) name.

    Used by the chat tool so a user can say 'email this to Dana' or give an
    address directly. Matching is case-insensitive: an exact email match wins,
    then an exact name match, then a name that contains the query.
    """

    needle = (query or "").strip().lower()
    if not needle:
        return None

    contacts = await list_for_org(org_id)
    # Exact email match.
    for c in contacts:
        if (c.get("email") or "").strip().lower() == needle:
            return c
    # Exact name match.
    for c in contacts:
        if (c.get("name") or "").strip().lower() == needle:
            return c
    # Partial name match (first contact whose name contains the query).
    for c in contacts:
        if needle in (c.get("name") or "").strip().lower():
            return c
    return None
