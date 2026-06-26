"""Shared dependencies: database pool, LangGraph checkpointer, and LLM factory.

These helpers are designed so the walking skeleton runs even with no database
and no real OpenAI key. They degrade gracefully:

* ``get_pool``        -> asyncpg pool when DATABASE_URL is set, else None.
* ``get_checkpointer``-> AsyncPostgresSaver when DATABASE_URL is set, else an
                         in-memory MemorySaver.
* ``get_llm``         -> a ChatOpenAI instance, or a deterministic offline
                         DemoChatModel when DEMO_MODE is set or no key exists.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger("app.deps")

# ---------------------------------------------------------------------------
# Database pool (lazily created singleton)
# ---------------------------------------------------------------------------

# Module-level cache so the pool is created at most once per process.
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool | None:
    """Return a lazily-created asyncpg connection pool.

    Returns ``None`` when ``DATABASE_URL`` is not configured so callers can run
    in a DB-less mode for the walking skeleton. The pool is cached at module
    level and reused across requests.
    """
    global _pool

    if not settings.database_url:
        # No database configured: run without persistence.
        return None

    if _pool is None:
        # min_size=0 keeps startup cheap; the pool fills on demand.
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=0,
            max_size=10,
        )

    return _pool


async def close_pool() -> None:
    """Close the global pool if it was created. Used by the app lifespan."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# LangGraph checkpointer
# ---------------------------------------------------------------------------

# Cache for the checkpointer + its context manager (Postgres saver needs setup).
_checkpointer: Any | None = None
_checkpointer_cm: Any | None = None


async def get_checkpointer() -> Any:
    """Return a LangGraph checkpointer.

    When ``DATABASE_URL`` is set an ``AsyncPostgresSaver`` (durable, Postgres
    backed) is created and its schema initialized. Otherwise a lightweight
    in-memory ``MemorySaver`` is returned so the graph can run without a DB.
    """
    global _checkpointer, _checkpointer_cm

    if _checkpointer is not None:
        return _checkpointer

    if settings.database_url:
        try:
            # Import lazily so the dependency is only required when a DB is used.
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # from_conn_string returns an async context manager; we enter it
            # manually and keep the reference so it stays open for the app's life.
            _checkpointer_cm = AsyncPostgresSaver.from_conn_string(
                settings.database_url
            )
            _checkpointer = await _checkpointer_cm.__aenter__()
            # Create the checkpointer tables if they do not exist yet.
            await _checkpointer.setup()
            return _checkpointer
        except Exception as exc:  # noqa: BLE001 - degrade to in-memory saver
            # Either the Postgres saver package is not installed or the database
            # is unreachable. Fall back so the graph still runs (state is then
            # process-local and lost on restart).
            logger.warning(
                "AsyncPostgresSaver unavailable (%s); using in-memory checkpointer.",
                exc,
            )
            _checkpointer_cm = None
            _checkpointer = None

    # DB-less fallback: in-memory checkpointer (state lost on restart).
    from langgraph.checkpoint.memory import MemorySaver

    _checkpointer = MemorySaver()
    return _checkpointer


async def close_checkpointer() -> None:
    """Tear down the Postgres checkpointer context manager if it was opened."""
    global _checkpointer, _checkpointer_cm
    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
        _checkpointer_cm = None
    _checkpointer = None


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


def get_llm(model: str | None = None, **kwargs: Any) -> Any:
    """Return a chat model configured from settings.

    In deterministic DEMO MODE (``DEMO_MODE`` truthy OR no ``OPENAI_API_KEY``
    configured) this returns an offline, reproducible :class:`DemoChatModel` so
    live demos and offline runs never flake or touch the network. Otherwise it
    returns a real ``ChatOpenAI`` instance.

    Args:
        model: Optional model override; defaults to ``settings.openai_model``.
        **kwargs: Extra keyword args forwarded to the model (e.g. temperature,
            streaming). Ignored by the demo model.
    """
    # Import lazily to keep the dependency surface small and avoid any import
    # cycle with modules that import ``app.deps``.
    from app.demo import demo_mode_enabled, get_demo_llm

    if demo_mode_enabled():
        logger.info("DEMO_MODE active: using deterministic offline chat model.")
        return get_demo_llm(model=model or settings.openai_model, **kwargs)

    # A request timeout plus bounded retries keep live runs from hanging: without
    # them a slow or stuck OpenAI call would block the planner's first node for
    # minutes. Caller kwargs win, so an explicit timeout/max_retries is preserved.
    return ChatOpenAI(
        model=model or settings.openai_model,
        api_key=settings.openai_api_key or "sk-placeholder",
        base_url=settings.openai_base_url,
        **{"timeout": 30.0, "max_retries": 2, **kwargs},
    )
