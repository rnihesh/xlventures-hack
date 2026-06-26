"""Async repositories backing optional Postgres persistence.

Each repository wraps an asyncpg pool (built from ``DATABASE_URL`` via
``app.deps.get_pool``) and degrades to a graceful no-op when the pool is
``None``, so the application behaves identically offline (in-memory only) and
online (durable). The convenience factories below build a repository bound to
the process-wide pool; pass ``get_pool()``'s result yourself to share a pool.
"""

from __future__ import annotations

from typing import Optional

import asyncpg

from app.repositories.episodes import EpisodesRepository
from app.repositories.recommendations import RecommendationsRepository
from app.repositories.runs import RunsRepository

__all__ = [
    "RunsRepository",
    "RecommendationsRepository",
    "EpisodesRepository",
    "get_runs_repository",
    "get_recommendations_repository",
    "get_episodes_repository",
]


async def _pool() -> Optional[asyncpg.Pool]:
    """Resolve the shared asyncpg pool (None offline). Imported lazily to avoid
    any import cycle with ``app.deps``."""
    from app.deps import get_pool

    return await get_pool()


async def get_runs_repository() -> RunsRepository:
    """Return a RunsRepository bound to the shared pool (no-op when offline)."""
    return RunsRepository(await _pool())


async def get_recommendations_repository() -> RecommendationsRepository:
    """Return a RecommendationsRepository bound to the shared pool."""
    return RecommendationsRepository(await _pool())


async def get_episodes_repository() -> EpisodesRepository:
    """Return an EpisodesRepository bound to the shared pool."""
    return EpisodesRepository(await _pool())
