"""Authentication API: signup, email verification, login, logout, and me.

Multi-tenant: every signup creates a fresh org and an (unverified) owner user
in it. A verification email is sent via SES; when SES is unavailable (no AWS
creds, no sender, dev), the user is auto-verified and the link is logged so the
flow still completes offline. Login issues an httpOnly ``nba_session`` JWT
cookie and rejects unverified users. ``/auth/me`` returns the current principal
and org from that cookie.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field

from app.auth.deps import get_current_user
from app.auth.security import (
    SESSION_COOKIE,
    SESSION_TTL,
    create_session_token,
    hash_password,
    verify_password,
)
from app.config import settings
from app.repositories import users as users_repo
from app.services import google_oauth
from app.services.email import send_verification

logger = logging.getLogger("app.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# Single-use CSRF state nonces for the Google sign-in flow. The user is not yet
# authenticated, so state is kept in a process-local set (validated by value),
# not bound to a session.
_GOOGLE_STATES: set[str] = set()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str | None = None
    org_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RenameOrgRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name"),
        "role": user.get("role", "member"),
        "org_id": user["org_id"],
        "email_verified": bool(user.get("email_verified")),
    }


def _set_session_cookie(response: Response, token: str) -> None:
    """Attach the httpOnly session cookie. ``secure`` is off in dev (http)."""

    secure = settings.app_env.lower() in {"production", "prod", "staging"}
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        domain=settings.cookie_domain or None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest) -> dict:
    """Create an org + user, send a verification email (or auto-verify in dev)."""

    existing = await users_repo.get_user_by_email(payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    org = await users_repo.create_org(name=payload.org_name)
    token = uuid.uuid4().hex
    user = await users_repo.create_user(
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        org_id=org["id"],
        role="owner",
        email_verified=False,
        verification_token=token,
    )

    link = f"{settings.app_base_url.rstrip('/')}/verify?token={token}"
    # send_verification is a synchronous boto3/SES call; offload it so the
    # signup request never blocks the event loop on the SES round-trip (the
    # offline / no-creds path returns before any network).
    result = await run_in_threadpool(send_verification, payload.email, link)

    is_dev = settings.app_env.lower() not in {"production", "prod", "staging"}
    auto_verified = False
    if not result.get("sent"):
        if not is_dev:
            # Production fails closed: never auto-verify or leak the link when the
            # verification email could not be delivered.
            raise HTTPException(
                status_code=503,
                detail="verification email could not be sent, please try again later",
            )
        # Dev convenience only: auto-verify so local testing is not blocked. Log a
        # non-secret marker (no token / link).
        await users_repo.set_verified(user["id"])
        auto_verified = True
        logger.debug("dev auto-verify user_id=%s (email not sent)", user["id"])

    user = await users_repo.get_user(user["id"]) or user
    response = {
        "user": _public_user(user),
        "org": org,
        "email_sent": bool(result.get("sent")),
        "auto_verified": auto_verified,
    }
    # Surface the verify link ONLY in dev when email could not be sent.
    if not result.get("sent") and is_dev:
        response["verify_url"] = link
    return response


@router.get("/verify")
async def verify(token: str) -> dict:
    """Mark the user owning ``token`` as verified."""

    user = await users_repo.get_user_by_verification_token(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token.",
        )
    await users_repo.set_verified(user["id"])
    return {"verified": True, "email": user["email"]}


@router.post("/login")
async def login(payload: LoginRequest, response: Response) -> dict:
    """Verify credentials, set the session cookie, and return user + org."""

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
    )

    user = await users_repo.get_user_by_email(payload.email)
    if user is None or not verify_password(payload.password, user.get("password_hash", "")):
        raise invalid

    if not user.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before signing in.",
        )

    org = await users_repo.get_org(user["org_id"])
    token = create_session_token(user["id"], user["org_id"])
    _set_session_cookie(response, token)
    return {"user": _public_user(user), "org": org}


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear the session cookie."""

    response.delete_cookie(
        key=SESSION_COOKIE, path="/", domain=settings.cookie_domain or None
    )
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    """Return the current authenticated user and org, or 401."""

    org = await users_repo.get_org(user["org_id"])
    return {"user": user, "org": org}


@router.put("/org")
async def rename_org(
    payload: RenameOrgRequest, user: dict = Depends(get_current_user)
) -> dict:
    """Rename the current user's org (workspace) and return the updated org."""

    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Workspace name cannot be empty.",
        )
    org = await users_repo.rename_org(user["org_id"], name)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found."
        )
    return {"org": org}


# ---------------------------------------------------------------------------
# Sign in with Google (OAuth as an authentication method, not a mail connector)
# ---------------------------------------------------------------------------


class GoogleLoginRequest(BaseModel):
    code: str
    state: str = ""


_GOOGLE_STATE_COOKIE = "google_oauth_state"


@router.get("/google/start")
async def google_start(response: Response) -> dict:
    """Return the Google consent URL for signing in, with a CSRF state nonce that
    is also bound to this browser via a short-lived httpOnly cookie."""

    import secrets

    if not google_oauth.is_configured():
        return {"configured": False, "url": None}
    state = secrets.token_urlsafe(32)
    if len(_GOOGLE_STATES) > 1000:
        _GOOGLE_STATES.clear()
    _GOOGLE_STATES.add(state)
    response.set_cookie(
        key=_GOOGLE_STATE_COOKIE,
        value=state,
        max_age=600,
        httponly=True,
        secure=settings.app_env.lower() in {"production", "prod", "staging"},
        samesite="lax",
        path="/",
        domain=settings.cookie_domain or None,
    )
    return {"configured": True, "url": google_oauth.consent_url(state=state)}


@router.post("/google/exchange")
async def google_exchange(
    body: GoogleLoginRequest, request: Request, response: Response
) -> dict:
    """Complete Google sign-in: validate state, resolve the Google account email,
    find or create the user (+ a personal org for first-time users), and set the
    session cookie."""

    import secrets

    # State must match BOTH the per-browser cookie set on /google/start AND the
    # single-use server set. The cookie binds the flow to the initiating agent
    # (the shared set alone is not enough against login CSRF).
    cookie_state = request.cookies.get(_GOOGLE_STATE_COOKIE)
    response.delete_cookie(
        _GOOGLE_STATE_COOKIE, path="/", domain=settings.cookie_domain or None
    )
    if (
        not body.state
        or not cookie_state
        or not secrets.compare_digest(cookie_state, body.state)
        or body.state not in _GOOGLE_STATES
    ):
        raise HTTPException(status_code=400, detail="invalid_state")
    _GOOGLE_STATES.discard(body.state)

    # exchange_code performs synchronous httpx calls to Google; offload it so
    # the token exchange never blocks the event loop.
    result = await run_in_threadpool(google_oauth.exchange_code, body.code)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "google_error"))
    email = (result.get("tokens") or {}).get("email")
    if not email:
        raise HTTPException(status_code=400, detail="no_email_from_google")

    user = await users_repo.get_user_by_email(email)
    if user is None:
        handle = email.split("@")[0]
        org = await users_repo.create_org(name=f"{handle}'s workspace")
        user = await users_repo.create_user(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(24)),
            name=handle,
            org_id=org["id"],
            role="owner",
            email_verified=True,
            verification_token=None,
        )

    org = await users_repo.get_org(user["org_id"])
    token = create_session_token(user["id"], user["org_id"])
    _set_session_cookie(response, token)
    return {"user": _public_user(user), "org": org}
