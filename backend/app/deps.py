"""Shared dependencies: database pool, LangGraph checkpointer, and LLM factory.

These helpers are designed so the walking skeleton runs even with no database
and no real OpenAI key. They degrade gracefully:

* ``get_pool``        -> asyncpg pool when DATABASE_URL is set, else None.
* ``get_checkpointer``-> AsyncPostgresSaver when DATABASE_URL is set, else an
                         in-memory MemorySaver.
* ``get_llm``         -> a configured ChatOpenAI instance.
"""

from __future__ import annotations

from typing import Any

import asyncpg
from langchain_openai import ChatOpenAI

from app.config import settings

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
        # Import lazily so the dependency is only required when a DB is used.
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # from_conn_string returns an async context manager; we enter it
        # manually and keep the reference so it stays open for the app's life.
        _checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
        _checkpointer = await _checkpointer_cm.__aenter__()
        # Create the checkpointer tables if they do not exist yet.
        await _checkpointer.setup()
        return _checkpointer

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


def get_llm(model: str | None = None, **kwargs: Any) -> ChatOpenAI:
    """Return a ChatOpenAI configured from settings.

    Args:
        model: Optional model override; defaults to ``settings.openai_model``.
        **kwargs: Extra keyword args forwarded to ChatOpenAI (e.g. temperature,
            streaming).
    """
    return ChatOpenAI(
        model=model or settings.openai_model,
        api_key=settings.openai_api_key or "sk-placeholder",
        base_url=settings.openai_base_url,
        **kwargs,
    )
