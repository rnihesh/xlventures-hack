"""FastAPI dependencies for the authenticated principal.

``get_current_user`` reads the ``nba_session`` cookie, validates the JWT, loads
the user, and returns a sanitized user dict (no password hash). ``get_current_org``
returns just the org id. Both raise 401 when the session is missing or invalid,
so user-facing endpoints can simply depend on them. The machine-token
``require_auth`` for backend-to-backend endpoints lives separately in app.deps.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.auth.security import SESSION_COOKIE, decode_session_token
from app.repositories import users as users_repo


def client_ip(request: Request) -> str | None:
    """Best-effort real client IP, honoring the reverse proxy's X-Forwarded-For."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Strip secret fields from a user row before returning it to callers."""

    from app.config import settings

    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name"),
        "role": user.get("role", "member"),
        "org_id": user["org_id"],
        "email_verified": bool(user.get("email_verified")),
        "is_admin": settings.is_admin(user.get("email")),
    }


async def get_current_user(request: Request) -> dict[str, Any]:
    """Return the current authenticated user, or raise 401.

    Validates the session cookie, then confirms the user still exists. The
    returned dict is safe to serialize (the password hash is removed).
    """

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = request.cookies.get(SESSION_COOKIE)
    claims = decode_session_token(token or "")
    if not claims:
        raise unauthorized

    user_id = claims.get("user_id") or claims.get("sub")
    if not user_id:
        raise unauthorized

    user = await users_repo.get_user(user_id)
    if user is None:
        raise unauthorized

    return _public_user(user)


async def get_current_org(
    user: dict[str, Any] = Depends(get_current_user),
) -> str:
    """Return the org id of the current authenticated user, or raise 401."""

    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return org_id
