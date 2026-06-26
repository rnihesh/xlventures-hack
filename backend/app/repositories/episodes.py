"""Async repository for learning episodes and their outcomes.

Wraps an asyncpg pool to persist and query the ``episodes`` table (one row per
decision episode) plus an append-only ``outcomes`` audit log. Every method is a
graceful no-op (returns ``None`` / empty) when the pool is ``None`` so the
Memory store falls back to its in-memory + seeded behavior offline.

Episodes are stored both as structured columns (for indexing / querying) and as
a full JSONB ``payload`` so they round-trip losslessly back into ``Episode``
models on load.
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


def _status_of(episode: Dict[str, Any]) -> str:
    """Derive a top-level status from an episode's embedded outcome."""
    outcome = episode.get("outcome") or {}
    decision = outcome.get("decision") if isinstance(outcome, dict) else None
    return decision or "pending"


class EpisodesRepository:
    """Persist and query learning episodes and outcome audit rows."""

    def __init__(self, pool: Optional[asyncpg.Pool]) -> None:
        self._pool = pool

    @property
    def enabled(self) -> bool:
        """True when a pool is available (durable learning memory)."""
        return self._pool is not None

    async def save(self, episode: Dict[str, Any]) -> Optional[str]:
        """Upsert an episode (full ``Episode.model_dump()`` dict).

        Returns the episode id, or None when persistence is disabled.
        """
        if self._pool is None:
            return None
        episode_id = episode.get("id")
        if not episode_id:
            return None
        await self._pool.execute(
            """
            INSERT INTO episodes (
                id, account_id, domain, situation, action_key,
                recommendation, preferred_action_key, phase,
                outcome, status, payload, created_at
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6::jsonb, $7, $8,
                $9::jsonb, $10, $11::jsonb,
                COALESCE($12::timestamptz, now())
            )
            ON CONFLICT (id) DO UPDATE SET
                account_id = EXCLUDED.account_id,
                domain = EXCLUDED.domain,
                situation = EXCLUDED.situation,
                action_key = EXCLUDED.action_key,
                recommendation = EXCLUDED.recommendation,
                preferred_action_key = EXCLUDED.preferred_action_key,
                phase = EXCLUDED.phase,
                outcome = EXCLUDED.outcome,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = now()
            """,
            episode_id,
            episode.get("account_id"),
            episode.get("domain"),
            episode.get("situation") or "",
            episode.get("action_key"),
            _dumps(episode.get("recommendation") or {}),
            episode.get("preferred_action_key"),
            episode.get("phase") or "live",
            _dumps(episode.get("outcome")),
            _status_of(episode),
            _dumps(episode),
            episode.get("created_at"),
        )
        return episode_id

    async def record_outcome(
        self, episode: Dict[str, Any], outcome: Optional[Dict[str, Any]] = None
    ) -> None:
        """Persist an episode's updated outcome and append an audit row."""
        if self._pool is None:
            return
        await self.save(episode)

        episode_id = episode.get("id")
        outcome = outcome or episode.get("outcome") or {}
        decision = outcome.get("decision", "pending") if isinstance(outcome, dict) else "pending"
        await self._pool.execute(
            """
            INSERT INTO outcomes (episode_id, decision, status, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            episode_id,
            decision,
            decision,
            _dumps(outcome),
        )

    async def get(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Return a single episode payload by id, or None when missing."""
        if self._pool is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT payload FROM episodes WHERE id = $1", episode_id
        )
        return _loads(row["payload"]) if row else None

    async def list_all(self) -> List[Dict[str, Any]]:
        """Return every stored episode payload (oldest first); empty offline."""
        if self._pool is None:
            return []
        rows = await self._pool.fetch(
            "SELECT payload FROM episodes ORDER BY created_at ASC, id ASC"
        )
        return [_loads(r["payload"]) for r in rows]
