"""FastAPI application factory.

Wires together configuration, CORS, the lifespan (which best-effort initializes
the database pool and LangGraph checkpointer), and the API routers. Routers are
imported lazily inside ``create_app`` to avoid circular imports.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.deps import (
    close_checkpointer,
    close_pool,
    get_checkpointer,
    get_pool,
)

logger = logging.getLogger("app.main")


def _resolve_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_forwarded_ip = forwarded_for.split(",")[0].strip()
        if first_forwarded_ip:
            return first_forwarded_ip

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "-"


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

    # Hydrate the episodic memory store from the database so the learning,
    # eval-outcome, and account-timeline surfaces see every org's persisted
    # decisions (not just the in-memory seeds + this-process writes). Without
    # this, a real org's durable episodes only appear after a write/recall.
    try:
        from app.memory.store import get_memory

        await get_memory()._ensure_db()
        logger.info("Memory store hydrated from database.")
    except Exception as exc:  # noqa: BLE001 - best effort startup
        logger.warning("Failed to hydrate memory store: %s", exc)

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

    @app.middleware("http")
    async def log_request_ip(request: Request, call_next):
        response = await call_next(request)
        logger.info(
            "%s %s status=%s client_ip=%s remote_addr=%s xff=%s",
            request.method,
            request.url.path,
            response.status_code,
            _resolve_client_ip(request),
            request.client.host if request.client and request.client.host else "-",
            request.headers.get("x-forwarded-for") or "-",
        )
        return response

    # CORS for the Next.js frontend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import routers lazily here to avoid import cycles with app.deps/app.config.
    from app.api import (
        accounts,
        admin,
        agents,
        auth,
        contacts,
        domains,
        health,
        ingest,
        integrations,
        passkey,
        rules,
        runs,
        whatif,
        workflow,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(passkey.router)
    app.include_router(runs.router)
    app.include_router(accounts.router)
    app.include_router(domains.router)
    app.include_router(whatif.router)
    app.include_router(ingest.router)
    app.include_router(integrations.router)
    app.include_router(contacts.router)
    app.include_router(rules.router)
    app.include_router(agents.router)
    app.include_router(admin.router)
    app.include_router(workflow.router)

    # Generic agentic chatbot over the whole platform (offline-safe).
    from app.api import chat

    app.include_router(chat.router)

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
