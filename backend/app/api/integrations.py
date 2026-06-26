"""Integrations API: per-org outbound connectors.

Lets each org configure how the platform sends on its behalf:

* ``GET    /integrations``                -> list this org's connectors + status.
* ``PUT    /integrations/{kind}``         -> save a connector's config.
* ``DELETE /integrations/{kind}``         -> remove a connector.
* ``GET    /integrations/google/start``   -> Google consent URL for OAuth.
* ``POST   /integrations/google/exchange``-> exchange an OAuth code for tokens.

Every endpoint is behind the user session cookie (``Depends(current_org)``) and
scoped to the caller's org. Everything is offline-safe: with no database the
connectors fall back to an in-memory store, and the Google OAuth helpers return
a graceful "not configured" status rather than raising when the client id /
secret are unset.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api._org import current_org
from app.repositories import connectors as connectors_repo
from app.services import google_oauth

router = APIRouter(prefix="/integrations", tags=["integrations"])
logger = logging.getLogger("app.api.integrations")

# Config keys that are secret and must never be echoed back to the client.
_SECRET_KEYS = {"access_token", "refresh_token", "aws_secret_access_key"}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ConnectorIn(BaseModel):
    """Body for PUT /integrations/{kind}: the connector config and an optional status."""

    config: Dict[str, Any] = {}
    status: Optional[str] = None


class GoogleExchangeIn(BaseModel):
    """Body for POST /integrations/google/exchange."""

    code: str
    state: str = ""


# CSRF protection: the random OAuth state generated on /google/start, kept
# server-side keyed by the initiating org, and required to match on exchange.
# Single-shot (popped after use). Process-local; fine for a single instance.
_PENDING_OAUTH_STATE: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _public(record: Dict[str, Any]) -> Dict[str, Any]:
    """Project a connector for the client, masking secret config values."""

    config = record.get("config") or {}
    safe_config: Dict[str, Any] = {}
    for key, value in config.items():
        if key in _SECRET_KEYS and value:
            safe_config[key] = "********"
        else:
            safe_config[key] = value
    return {
        "kind": record.get("kind"),
        "status": record.get("status", "not_configured"),
        "config": safe_config,
        "updated_at": record.get("updated_at"),
    }


def _derive_status(kind: str, config: Dict[str, Any]) -> str:
    """Infer a connector status from whether its required fields are present."""

    if kind == "ses":
        return "connected" if config.get("sender_email") else "not_configured"
    if kind == "slack":
        return "connected" if config.get("webhook_url") else "not_configured"
    if kind == "google":
        return "connected" if config.get("access_token") or config.get("refresh_token") else "not_configured"
    return "connected" if config else "not_configured"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_integrations(org_id: str = Depends(current_org)) -> Dict[str, Any]:
    """List this org's connectors plus the Google OAuth availability flag."""

    records = await connectors_repo.list(org_id)
    return {
        "connectors": [_public(r) for r in records],
        "google_oauth_configured": google_oauth.is_configured(),
    }


@router.put("/{kind}")
async def save_integration(
    kind: str,
    body: ConnectorIn,
    org_id: str = Depends(current_org),
) -> Dict[str, Any]:
    """Save a connector's config under the caller's org."""

    if kind not in connectors_repo.KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid kind; expected one of {list(connectors_repo.KINDS)}",
        )

    config = body.config or {}
    # When updating google config, preserve any existing tokens not re-sent.
    if kind == "google":
        existing = await connectors_repo.get(org_id, kind)
        if existing:
            merged = dict(existing.get("config") or {})
            merged.update({k: v for k, v in config.items() if v not in (None, "", "********")})
            config = merged

    status = body.status or _derive_status(kind, config)
    record = await connectors_repo.upsert(org_id, kind, config, status)
    return _public(record)


@router.delete("/{kind}")
async def delete_integration(
    kind: str,
    org_id: str = Depends(current_org),
) -> Dict[str, Any]:
    """Remove a connector from the caller's org."""

    if kind not in connectors_repo.KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid kind; expected one of {list(connectors_repo.KINDS)}",
        )
    removed = await connectors_repo.delete(org_id, kind)
    return {"deleted": removed, "kind": kind}


@router.post("/slack/test")
async def slack_test(org_id: str = Depends(current_org)) -> Dict[str, Any]:
    """Post a sample message to the org's saved Slack webhook to confirm it works."""

    from app.services.slack import post_message

    connector = await connectors_repo.get(org_id, "slack")
    webhook = ((connector or {}).get("config") or {}).get("webhook_url")
    if not webhook:
        raise HTTPException(status_code=400, detail="slack_not_configured")
    result = post_message(
        webhook,
        "Aperture test: your Slack handoff is connected. Approved plays will post here.",
    )
    return result


@router.get("/google/start")
async def google_start(org_id: str = Depends(current_org)) -> Dict[str, Any]:
    """Return the Google consent URL, or a graceful not-configured status.

    Binds the flow to this org with a high-entropy single-shot state nonce so the
    callback cannot be forged (CSRF).
    """

    import secrets

    state = secrets.token_urlsafe(32)
    url = google_oauth.consent_url(state=state)
    if not url:
        return {"configured": False, "url": None, "reason": "google_not_configured"}
    _PENDING_OAUTH_STATE[org_id] = state
    return {"configured": True, "url": url}


@router.post("/google/exchange")
async def google_exchange(
    body: GoogleExchangeIn,
    org_id: str = Depends(current_org),
) -> Dict[str, Any]:
    """Exchange an OAuth code for tokens and store them on the org's connector."""

    import secrets

    expected = _PENDING_OAUTH_STATE.pop(org_id, None)
    if not expected or not body.state or not secrets.compare_digest(expected, body.state):
        return {"connected": False, "reason": "invalid_state"}

    result = google_oauth.exchange_code(body.code)
    if not result.get("ok"):
        return {
            "connected": False,
            "reason": result.get("reason", "google_error"),
            "detail": result.get("detail"),
        }

    tokens = result.get("tokens") or {}
    record = await connectors_repo.upsert(org_id, "google", tokens, status="connected")
    return {"connected": True, "connector": _public(record)}
