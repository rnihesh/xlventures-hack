"""Async repository for chat sessions (multi-conversation history).

Persists conversations to the ``chat_sessions`` table via the asyncpg pool when
a database is configured. When there is no pool (offline / no DATABASE_URL) it
falls back to a process-local in-memory store so the chat still works, just not
durably. The full transcript is kept as JSONB so it round-trips to the UI.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.deps import get_pool

# Process-local fallback when no database is configured.
_MEMORY: Dict[str, Dict[str, Any]] = {}


def _row_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "title": row.get("title") or "New chat",
        "updated_at": row["updated_at"],
    }


async def list_sessions(org_id: str = "org_demo") -> List[Dict[str, Any]]:
    """List the org's sessions (id, title, updated_at), newest updated first."""

    pool = await get_pool()
    if pool is None:
        items = sorted(
            (s for s in _MEMORY.values() if s.get("org_id") == org_id),
            key=lambda s: s.get("updated_at", ""),
            reverse=True,
        )
        return [_row_summary(s) for s in items]

    rows = await pool.fetch(
        "SELECT id, title, updated_at FROM chat_sessions "
        "WHERE org_id = $1 ORDER BY updated_at DESC",
        org_id,
    )
    return [
        {"id": r["id"], "title": r["title"], "updated_at": r["updated_at"].isoformat()}
        for r in rows
    ]


async def get_session(
    session_id: str, org_id: str = "org_demo"
) -> Optional[Dict[str, Any]]:
    """Return one of the org's sessions with its full turns, or None when absent."""

    pool = await get_pool()
    if pool is None:
        s = _MEMORY.get(session_id)
        if s is None or s.get("org_id") != org_id:
            return None
        return {k: v for k, v in s.items() if k != "org_id"}

    row = await pool.fetchrow(
        "SELECT id, title, turns, updated_at FROM chat_sessions "
        "WHERE id = $1 AND org_id = $2",
        session_id,
        org_id,
    )
    if row is None:
        return None
    turns = row["turns"]
    if isinstance(turns, str):
        turns = json.loads(turns)
    return {
        "id": row["id"],
        "title": row["title"],
        "turns": turns or [],
        "updated_at": row["updated_at"].isoformat(),
    }


async def upsert_session(
    session_id: str, title: str, turns: List[Dict[str, Any]], org_id: str = "org_demo"
) -> Dict[str, Any]:
    """Create or update one of the org's sessions, bumping updated_at.

    The conflict clause keeps the row pinned to its original org so a session id
    can never be reassigned to a different tenant.
    """

    pool = await get_pool()
    if pool is None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        existing = _MEMORY.get(session_id)
        if existing is not None and existing.get("org_id") != org_id:
            # Do not let another org overwrite an existing session id.
            return {"id": session_id, "title": existing.get("title"), "updated_at": existing.get("updated_at")}
        _MEMORY[session_id] = {
            "id": session_id,
            "title": title or "New chat",
            "turns": turns,
            "org_id": org_id,
            "updated_at": now,
        }
        return {"id": session_id, "title": title, "updated_at": now}

    row = await pool.fetchrow(
        """
        INSERT INTO chat_sessions (id, title, turns, org_id, updated_at)
        VALUES ($1, $2, $3::jsonb, $4, now())
        ON CONFLICT (id) DO UPDATE
          SET title = EXCLUDED.title,
              turns = EXCLUDED.turns,
              updated_at = now()
          WHERE chat_sessions.org_id = EXCLUDED.org_id
        RETURNING id, title, updated_at
        """,
        session_id,
        title or "New chat",
        json.dumps(turns),
        org_id,
    )
    if row is None:
        # Conflict on a session owned by another org: return its current state.
        existing = await get_session(session_id, org_id)
        return existing or {"id": session_id, "title": title, "updated_at": None}
    return {
        "id": row["id"],
        "title": row["title"],
        "updated_at": row["updated_at"].isoformat(),
    }


async def delete_session(session_id: str, org_id: str = "org_demo") -> None:
    """Delete one of the org's sessions. No-op when it does not exist."""

    pool = await get_pool()
    if pool is None:
        s = _MEMORY.get(session_id)
        if s is not None and s.get("org_id") == org_id:
            _MEMORY.pop(session_id, None)
        return
    await pool.execute(
        "DELETE FROM chat_sessions WHERE id = $1 AND org_id = $2",
        session_id,
        org_id,
    )
