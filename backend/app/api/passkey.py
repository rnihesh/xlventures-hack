"""WebAuthn passkey authentication.

Two ceremonies:

* Registration (signed-in user adds a passkey): /register/options then
  /register/verify. The new credential is stored against the user.
* Login (passwordless): /login/options then /login/verify. A verified assertion
  issues the same session cookie password login does.

Challenges are held in a short-lived in-memory store keyed by user id
(registration) or a random handle returned to the client (login). The crypto is
handled by the ``webauthn`` library; we never roll our own.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from typing import Any, Optional

import webauthn
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.api.auth import _set_session_cookie
from app.auth.deps import _public_user, client_ip, get_current_user
from app.auth.security import create_session_token
from app.config import settings
from app.repositories import passkeys as repo
from app.repositories import users as users_repo

logger = logging.getLogger("app.api.passkey")

router = APIRouter(prefix="/auth/passkey", tags=["auth"])

# challenge store: key -> (challenge bytes, expiry epoch)
_CHALLENGES: dict[str, tuple[bytes, float]] = {}
_TTL = 300.0


def _gc() -> None:
    now = time.time()
    for k in [k for k, (_c, e) in _CHALLENGES.items() if e < now]:
        _CHALLENGES.pop(k, None)


def _put(key: str, challenge: bytes) -> None:
    _gc()
    _CHALLENGES[key] = (challenge, time.time() + _TTL)


def _take(key: str) -> Optional[bytes]:
    item = _CHALLENGES.pop(key, None)
    if not item:
        return None
    challenge, exp = item
    return challenge if exp > time.time() else None


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --- Registration (requires an authenticated user) -------------------------


@router.post("/register/options")
async def register_options(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    existing = await repo.list_for_user(user["id"])
    exclude = [PublicKeyCredentialDescriptor(id=_unb64u(c["credential_id"])) for c in existing]
    options = webauthn.generate_registration_options(
        rp_id=settings.rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=user["id"].encode(),
        user_name=user["email"],
        user_display_name=user.get("name") or user["email"],
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    _put(f"reg:{user['id']}", options.challenge)
    return json.loads(webauthn.options_to_json(options))


class RegVerifyIn(BaseModel):
    credential: dict[str, Any]
    label: Optional[str] = None


@router.post("/register/verify")
async def register_verify(
    body: RegVerifyIn, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    challenge = _take(f"reg:{user['id']}")
    if challenge is None:
        raise HTTPException(status_code=400, detail="Registration expired, try again.")
    try:
        verified = webauthn.verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_origin=settings.rp_origin,
            expected_rp_id=settings.rp_id,
        )
    except Exception as exc:  # noqa: BLE001 - any verification failure is a 400
        logger.info("passkey registration failed: %s", exc)
        raise HTTPException(status_code=400, detail="Passkey verification failed.") from exc

    await repo.add_credential(
        user_id=user["id"],
        credential_id=_b64u(verified.credential_id),
        public_key=_b64u(verified.credential_public_key),
        sign_count=verified.sign_count,
        transports=None,
        label=(body.label or "Passkey").strip()[:60],
    )
    return {"ok": True}


@router.get("")
async def list_passkeys(user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    rows = await repo.list_for_user(user["id"])
    return [
        {
            "credential_id": r["credential_id"],
            "label": r.get("label"),
            "created_at": r.get("created_at"),
            "last_used_at": r.get("last_used_at"),
        }
        for r in rows
    ]


# --- Login (passwordless) --------------------------------------------------


class LoginOptionsIn(BaseModel):
    email: Optional[str] = None


@router.post("/login/options")
async def login_options(body: LoginOptionsIn) -> dict[str, Any]:
    allow: list[PublicKeyCredentialDescriptor] = []
    if body.email:
        u = await users_repo.get_user_by_email(body.email.strip().lower())
        if u:
            for c in await repo.list_for_user(u["id"]):
                allow.append(PublicKeyCredentialDescriptor(id=_unb64u(c["credential_id"])))
    options = webauthn.generate_authentication_options(
        rp_id=settings.rp_id,
        allow_credentials=allow or None,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    handle = uuid.uuid4().hex
    _put(f"login:{handle}", options.challenge)
    out = json.loads(webauthn.options_to_json(options))
    out["handle"] = handle
    return out


class LoginVerifyIn(BaseModel):
    credential: dict[str, Any]
    handle: str


@router.post("/login/verify")
async def login_verify(
    body: LoginVerifyIn, request: Request, response: Response
) -> dict[str, Any]:
    challenge = _take(f"login:{body.handle}")
    if challenge is None:
        raise HTTPException(status_code=400, detail="Login expired, try again.")
    cred_id = str(body.credential.get("id") or "")
    stored = await repo.get_by_credential_id(cred_id)
    if not stored:
        raise HTTPException(status_code=401, detail="Passkey not recognized.")
    try:
        verified = webauthn.verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.rp_id,
            expected_origin=settings.rp_origin,
            credential_public_key=_unb64u(stored["public_key"]),
            credential_current_sign_count=stored["sign_count"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("passkey login failed: %s", exc)
        raise HTTPException(status_code=401, detail="Passkey verification failed.") from exc

    await repo.update_sign_count(cred_id, verified.new_sign_count)
    user = await users_repo.get_user(stored["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="Account not found.")
    token = create_session_token(user["id"], user["org_id"])
    _set_session_cookie(response, token)
    await users_repo.touch_last_login(user["id"], client_ip(request), "passkey")
    org = await users_repo.get_org(user["org_id"])
    return {"user": _public_user(user), "org": org}
