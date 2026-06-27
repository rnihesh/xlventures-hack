"""Async repository for orgs and users (multi-tenant auth).

Persists to the ``orgs`` and ``users`` tables via the asyncpg pool when a
database is configured. With no pool (offline / no DATABASE_URL) it falls back
to a process-local in-memory store so signup, verification, and login still
round-trip in tests and demos, just not durably.

The in-memory store is pre-seeded with the Demo org and the demo user so the
offline path mirrors the migration seed (demo@niheshr.com / demo1234, verified).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.auth.security import hash_password
from app.deps import get_pool

# --- Demo seed (mirrors alembic 0005_auth) ----------------------------------
DEMO_ORG_ID = "org_demo"
DEMO_ORG_NAME = "Demo"
DEMO_USER_EMAIL = "demo@niheshr.com"
DEMO_USER_PASSWORD = "demo1234"

# Process-local fallbacks, keyed by id. Seeded lazily on first access so the
# bcrypt hash is computed at import time only when actually needed offline.
_ORGS: dict[str, dict[str, Any]] = {}
_USERS: dict[str, dict[str, Any]] = {}
_seeded = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_memory() -> None:
    """Populate the in-memory store with the Demo org and demo user once.

    Only seeds the known-password demo user in dev/demo environments so a
    production deployment never carries a backdoor account.
    """

    global _seeded
    if _seeded:
        return
    _seeded = True

    from app.config import settings

    if settings.app_env.lower() in {"production", "prod", "staging"}:
        return
    _ORGS[DEMO_ORG_ID] = {
        "id": DEMO_ORG_ID,
        "name": DEMO_ORG_NAME,
        "created_at": _now(),
    }
    demo_id = "user_demo"
    _USERS[demo_id] = {
        "id": demo_id,
        "email": DEMO_USER_EMAIL,
        "password_hash": hash_password(DEMO_USER_PASSWORD),
        "name": "Demo User",
        "role": "owner",
        "org_id": DEMO_ORG_ID,
        "email_verified": True,
        "verification_token": None,
        "created_at": _now(),
    }


def new_id(prefix: str) -> str:
    """Return a short prefixed unique id (e.g. ``org_ab12cd``)."""

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Orgs
# ---------------------------------------------------------------------------


async def create_org(name: str, org_id: str | None = None) -> dict[str, Any]:
    """Create an org and return it."""

    oid = org_id or new_id("org")
    pool = await get_pool()
    if pool is None:
        _seed_memory()
        org = {"id": oid, "name": name, "created_at": _now()}
        _ORGS[oid] = org
        return dict(org)

    row = await pool.fetchrow(
        """
        INSERT INTO orgs (id, name)
        VALUES ($1, $2)
        RETURNING id, name, created_at
        """,
        oid,
        name,
    )
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"].isoformat(),
    }


async def get_org(org_id: str) -> dict[str, Any] | None:
    """Return one org by id, or None."""

    pool = await get_pool()
    if pool is None:
        _seed_memory()
        org = _ORGS.get(org_id)
        return dict(org) if org else None

    row = await pool.fetchrow(
        "SELECT id, name, created_at FROM orgs WHERE id = $1", org_id
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"].isoformat(),
    }


async def rename_org(org_id: str, name: str) -> dict[str, Any] | None:
    """Rename an org and return the updated record, or None if it is missing."""

    name = name.strip()
    pool = await get_pool()
    if pool is None:
        _seed_memory()
        org = _ORGS.get(org_id)
        if org is None:
            return None
        org["name"] = name
        return dict(org)

    row = await pool.fetchrow(
        "UPDATE orgs SET name = $2 WHERE id = $1 RETURNING id, name, created_at",
        org_id,
        name,
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"].isoformat(),
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def create_user(
    *,
    email: str,
    password_hash: str,
    name: str | None,
    org_id: str,
    role: str = "member",
    email_verified: bool = False,
    verification_token: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create a user and return the full row (including secret fields)."""

    uid = user_id or new_id("user")
    email = email.strip().lower()
    pool = await get_pool()
    if pool is None:
        _seed_memory()
        user = {
            "id": uid,
            "email": email,
            "password_hash": password_hash,
            "name": name,
            "role": role,
            "org_id": org_id,
            "email_verified": email_verified,
            "verification_token": verification_token,
            "created_at": _now(),
        }
        _USERS[uid] = user
        return dict(user)

    row = await pool.fetchrow(
        """
        INSERT INTO users
            (id, email, password_hash, name, role, org_id,
             email_verified, verification_token)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, email, password_hash, name, role, org_id,
                  email_verified, verification_token, created_at
        """,
        uid,
        email,
        password_hash,
        name,
        role,
        org_id,
        email_verified,
        verification_token,
    )
    return _row_to_user(row)


async def get_user(user_id: str) -> dict[str, Any] | None:
    """Return one user by id, or None."""

    pool = await get_pool()
    if pool is None:
        _seed_memory()
        user = _USERS.get(user_id)
        return dict(user) if user else None

    row = await pool.fetchrow(
        """
        SELECT id, email, password_hash, name, role, org_id,
               email_verified, verification_token, created_at
        FROM users WHERE id = $1
        """,
        user_id,
    )
    return _row_to_user(row) if row else None


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Return one user by (case-insensitive) email, or None."""

    email = email.strip().lower()
    pool = await get_pool()
    if pool is None:
        _seed_memory()
        for user in _USERS.values():
            if user["email"] == email:
                return dict(user)
        return None

    row = await pool.fetchrow(
        """
        SELECT id, email, password_hash, name, role, org_id,
               email_verified, verification_token, created_at
        FROM users WHERE email = $1
        """,
        email,
    )
    return _row_to_user(row) if row else None


async def get_user_by_verification_token(token: str) -> dict[str, Any] | None:
    """Return the user owning ``token``, or None."""

    if not token:
        return None
    pool = await get_pool()
    if pool is None:
        _seed_memory()
        for user in _USERS.values():
            if user.get("verification_token") == token:
                return dict(user)
        return None

    row = await pool.fetchrow(
        """
        SELECT id, email, password_hash, name, role, org_id,
               email_verified, verification_token, created_at
        FROM users WHERE verification_token = $1
        """,
        token,
    )
    return _row_to_user(row) if row else None


async def set_verified(user_id: str) -> None:
    """Mark a user verified and clear its verification token."""

    pool = await get_pool()
    if pool is None:
        _seed_memory()
        user = _USERS.get(user_id)
        if user:
            user["email_verified"] = True
            user["verification_token"] = None
        return

    await pool.execute(
        """
        UPDATE users
        SET email_verified = TRUE, verification_token = NULL
        WHERE id = $1
        """,
        user_id,
    )


async def touch_last_login(user_id: str) -> None:
    """Record the user's most recent login time (best effort, never raises)."""

    pool = await get_pool()
    if pool is None:
        _seed_memory()
        user = _USERS.get(user_id)
        if user:
            user["last_login_at"] = _now()
        return
    try:
        await pool.execute(
            "UPDATE users SET last_login_at = now() WHERE id = $1", user_id
        )
    except Exception:  # noqa: BLE001 - column may be pre-migration; non-fatal
        pass


def _row_to_user(row: Any) -> dict[str, Any]:
    """Convert an asyncpg Record into a plain user dict."""

    created = row["created_at"]
    return {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "name": row["name"],
        "role": row["role"],
        "org_id": row["org_id"],
        "email_verified": bool(row["email_verified"]),
        "verification_token": row["verification_token"],
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }
