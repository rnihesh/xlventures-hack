"""Persistence for WebAuthn passkey credentials.

Degrades to an in-memory store when no database pool is configured, so passkey
registration and login still round-trip offline and in tests.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.deps import get_pool

logger = logging.getLogger("app.repositories.passkeys")

# Offline fallback store: credential_id -> row dict.
_MEM: dict[str, dict[str, Any]] = {}


async def add_credential(
    user_id: str,
    credential_id: str,
    public_key: str,
    sign_count: int,
    transports: Optional[str],
    label: Optional[str],
) -> None:
    pool = await get_pool()
    if pool is None:
        _MEM[credential_id] = {
            "user_id": user_id,
            "credential_id": credential_id,
            "public_key": public_key,
            "sign_count": sign_count,
            "transports": transports,
            "label": label,
        }
        return
    await pool.execute(
        """
        INSERT INTO webauthn_credentials
            (user_id, credential_id, public_key, sign_count, transports, label)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (credential_id) DO NOTHING
        """,
        user_id,
        credential_id,
        public_key,
        sign_count,
        transports,
        label,
    )


async def list_for_user(user_id: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        return [dict(r) for r in _MEM.values() if r["user_id"] == user_id]
    rows = await pool.fetch(
        "SELECT credential_id, public_key, sign_count, transports, label, created_at, "
        "last_used_at FROM webauthn_credentials WHERE user_id = $1 ORDER BY created_at",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_by_credential_id(credential_id: str) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        return _MEM.get(credential_id)
    row = await pool.fetchrow(
        "SELECT user_id, credential_id, public_key, sign_count FROM "
        "webauthn_credentials WHERE credential_id = $1",
        credential_id,
    )
    return dict(row) if row else None


async def update_sign_count(credential_id: str, sign_count: int) -> None:
    pool = await get_pool()
    if pool is None:
        if credential_id in _MEM:
            _MEM[credential_id]["sign_count"] = sign_count
        return
    await pool.execute(
        "UPDATE webauthn_credentials SET sign_count = $2, last_used_at = now() "
        "WHERE credential_id = $1",
        credential_id,
        sign_count,
    )


async def count_for_user(user_id: str) -> int:
    pool = await get_pool()
    if pool is None:
        return len([r for r in _MEM.values() if r["user_id"] == user_id])
    return int(await pool.fetchval(
        "SELECT count(*) FROM webauthn_credentials WHERE user_id = $1", user_id
    ) or 0)
