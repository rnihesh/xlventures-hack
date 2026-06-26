"""FastAPI application factory.

Wires together configuration, CORS, the lifespan (which best-effort initializes
the database pool and LangGraph checkpointer), and the API routers. Routers are
imported lazily inside ``create_app`` to avoid circular imports.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.deps import (
    close_checkpointer,
    close_pool,
    get_checkpointer,
    get_pool,
)

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down shared resources.

    Initialization is best-effort: failures (e.g. DB unreachable) are logged
    but do not prevent the app from starting, so the walking skeleton stays up.
    """
    # --- Startup ---------------------------------------------------------
    try:
        pool = await get_pool()
        app.state.pool = pool
        if pool is not None:
            logger.info("Database pool initialized.")
        else:
            logger.info("No DATABASE_URL set; running in DB-less mode.")
    except Exception as exc:  # noqa: BLE001 - best effort startup
        logger.warning("Failed to initialize database pool: %s", exc)
        app.state.pool = None

    try:
        app.state.checkpointer = await get_checkpointer()
        logger.info(
            "Checkpointer initialized (%s).",
            type(app.state.checkpointer).__name__,
        )
    except Exception as exc:  # noqa: BLE001 - best effort startup
        logger.warning("Failed to initialize checkpointer: %s", exc)
        app.state.checkpointer = None

    yield

    # --- Shutdown --------------------------------------------------------
    try:
        await close_checkpointer()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error closing checkpointer: %s", exc)

    try:
        await close_pool()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error closing pool: %s", exc)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for the Next.js frontend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import routers lazily here to avoid import cycles with app.deps/app.config.
    from app.api import accounts, domains, health, runs, whatif

    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(accounts.router)
    app.include_router(domains.router)
    app.include_router(whatif.router)

    # Learning, eval, execute, and policy routers are owned by other slices.
    # Include them when present so the app still boots if a slice has not landed.
    for module_name in ("learning", "eval", "execute", "policy"):
        try:
            module = __import__(f"app.api.{module_name}", fromlist=["router"])
            app.include_router(module.router)
        except Exception as exc:  # noqa: BLE001 - optional slice
            logger.warning("Skipping %s router: %s", module_name, exc)

    return app


app = create_app()
