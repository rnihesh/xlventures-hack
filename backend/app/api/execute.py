"""Action execution API.

Turns a recommendation into a real artifact with one call:

* ``POST /execute``           -> generate an email / CRM task / Slack handoff
                                 from a recommendation (or a stored run) plus
                                 account context, and record an audit entry.
* ``GET  /execute/{run_id}``  -> list the artifacts generated for a run.

Generated artifacts and their audit records are held in an in-memory store so
the feature works with no database. Generation itself is offline-safe: the
generators use the LLM only when ``OPENAI_API_KEY`` is set and otherwise fall
back to deterministic templates.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.actions import ARTIFACT_TYPES, generate_artifact
from app.actions.generators import _llm_available
from app.api._org import current_org
from app.config import settings
from app.repositories import connectors as connectors_repo
from app.services import email as email_service
from app.services import google_oauth
from app.services import slack as slack_service

router = APIRouter(tags=["execute"])

# In-memory store of generated artifacts keyed by run id. Each value is a list
# of audit records (most recent last). Artifacts not tied to a run are filed
# under the synthetic key below so GET still has somewhere to read them from.
_ARTIFACTS: Dict[str, List[Dict[str, Any]]] = {}
_UNATTACHED_KEY = "_unattached"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ExecuteIn(BaseModel):
    """Body for POST /execute.

    Provide either ``run_id`` (to pull the stored recommendation) or an inline
    ``recommendation`` object. ``account_id`` supplies account context; when a
    ``run_id`` is given its account is used as a fallback.
    """

    run_id: Optional[str] = None
    recommendation: Optional[Dict[str, Any]] = None
    account_id: Optional[str] = None
    artifact_type: str = Field(..., description="email | crm_task | slack")


class ExecuteOut(BaseModel):
    artifact: Dict[str, Any]
    audit: Dict[str, Any]


class SendIn(BaseModel):
    """Body for POST /execute/send.

    ``artifact_type`` is the channel to send through (``email`` via SES,
    ``gmail`` / ``google`` via the Gmail API, ``slack`` via webhook). ``artifact``
    is the generated content (e.g. ``{subject, body}`` for email, ``{message}``
    for slack). ``account_id`` supplies the recipient context; ``run_id`` ties
    the send to a stored run for auditing.
    """

    artifact_type: str = Field(..., description="email | gmail | google | slack")
    artifact: Dict[str, Any] = Field(default_factory=dict)
    account_id: Optional[str] = None
    run_id: Optional[str] = None


class SendOut(BaseModel):
    sent: bool
    reason: Optional[str] = None
    detail: Optional[Any] = None
    channel: Optional[str] = None


# ---------------------------------------------------------------------------
# Context resolution (best-effort, tolerant of missing slices)
# ---------------------------------------------------------------------------


def _lookup_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a run record from the runs slice, if that slice is loaded."""

    try:
        from app.api.runs import _RUNS
    except Exception:  # noqa: BLE001 - runs slice optional
        return None
    return _RUNS.get(run_id)


def _lookup_account(account_id: Optional[str]) -> Dict[str, Any]:
    """Resolve account context from the accounts seed, with a safe fallback."""

    if not account_id:
        return {}
    try:
        from app.api.accounts import _BY_ID

        account = _BY_ID.get(account_id)
        if account is not None:
            return account
    except Exception:  # noqa: BLE001 - accounts slice optional
        pass
    return {"account_id": account_id}


def _resolve_recommendation(body: ExecuteIn) -> tuple[Dict[str, Any], Optional[str]]:
    """Return the recommendation to act on plus the resolved account id."""

    rec: Optional[Dict[str, Any]] = body.recommendation
    account_id = body.account_id

    if rec is None and body.run_id:
        run = _lookup_run(body.run_id)
        if run is not None:
            rec = run.get("recommendation")
            account_id = account_id or run.get("account_id")

    if not isinstance(rec, dict) or not rec:
        raise HTTPException(
            status_code=422,
            detail="no recommendation available; pass 'recommendation' or a 'run_id' with a stored recommendation",
        )

    # Last resort for account context: the recommendation may carry it.
    account_id = account_id or rec.get("account_id")
    return rec, account_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/execute", response_model=ExecuteOut)
async def execute(body: ExecuteIn) -> ExecuteOut:
    """Generate an artifact from a recommendation and record an audit entry."""

    if body.artifact_type not in ARTIFACT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid artifact_type; expected one of {list(ARTIFACT_TYPES)}",
        )

    rec, account_id = _resolve_recommendation(body)
    account = _lookup_account(account_id)

    try:
        artifact = generate_artifact(body.artifact_type, rec, account)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    action = rec.get("action") if isinstance(rec.get("action"), dict) else {}
    audit: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "run_id": body.run_id,
        "account_id": account_id,
        "artifact_type": body.artifact_type,
        "action_key": action.get("key"),
        "recommendation_id": rec.get("id"),
        "source": "llm" if _llm_available() else "template",
        "created_at": _now_iso(),
        "artifact": artifact,
    }

    store_key = body.run_id or _UNATTACHED_KEY
    _ARTIFACTS.setdefault(store_key, []).append(audit)

    return ExecuteOut(artifact=artifact, audit=audit)


@router.get("/execute/{run_id}")
async def list_artifacts(run_id: str) -> List[Dict[str, Any]]:
    """List artifacts generated for a run, most recent first."""

    records = _ARTIFACTS.get(run_id, [])
    return list(reversed(records))


# ---------------------------------------------------------------------------
# Real send (used when the user clicks Send)
# ---------------------------------------------------------------------------


def _recipient_email(artifact: Dict[str, Any], account: Dict[str, Any]) -> Optional[str]:
    """Resolve the recipient email from the artifact, then the account profile."""

    to = artifact.get("to") or artifact.get("recipient")
    if to:
        return str(to)
    profile = account.get("profile") if isinstance(account, dict) else None
    if isinstance(profile, dict):
        for key in ("email", "contact_email", "owner_email"):
            if profile.get(key):
                return str(profile[key])
    for key in ("email", "contact_email"):
        if account.get(key):
            return str(account[key])
    return None


def _slack_text(artifact: Dict[str, Any]) -> str:
    """Resolve the message text from a slack (or generic) artifact."""

    return str(
        artifact.get("message")
        or artifact.get("text")
        or artifact.get("body")
        or ""
    )


@router.post("/execute/send", response_model=SendOut)
async def execute_send(
    body: SendIn,
    org_id: str = Depends(current_org),
) -> SendOut:
    """Actually send an artifact through the org's configured channel.

    Looks up the org connector for the channel and sends for real (email via
    SES, slack via webhook, gmail via the stored Google token). Offline or
    unconfigured channels return ``{sent: False, reason: '... not configured'}``
    rather than raising, so the click-to-send flow never crashes.
    """

    artifact = body.artifact or {}
    account = _lookup_account(body.account_id)
    kind = body.artifact_type.lower().strip()

    result: Dict[str, Any]

    if kind in ("email", "gmail", "google"):
        # All email sends go over SES from the single platform sender. There is
        # no per-org sender configuration; Google is a sign-in method, not a mail
        # connector.
        to = _recipient_email(artifact, account)
        if not to:
            result = {"sent": False, "reason": "no_recipient"}
        else:
            result = email_service.send_email(
                to=to,
                subject=str(artifact.get("subject") or "(no subject)"),
                body=str(artifact.get("body") or ""),
                sender=settings.ses_sender_email,
            )
        channel = "email"

    elif kind == "slack":
        connector = await connectors_repo.get(org_id, "slack")
        config = (connector or {}).get("config") or {}
        result = slack_service.post_message(
            config.get("webhook_url"), _slack_text(artifact)
        )
        channel = "slack"

    else:
        raise HTTPException(
            status_code=422,
            detail="invalid artifact_type; expected one of email | gmail | google | slack",
        )

    # Record an audit entry so the send shows up alongside generated artifacts.
    audit: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "run_id": body.run_id,
        "account_id": body.account_id,
        "channel": channel,
        "action": "send",
        "sent": bool(result.get("sent")),
        "reason": result.get("reason"),
        "created_at": _now_iso(),
    }
    store_key = body.run_id or _UNATTACHED_KEY
    _ARTIFACTS.setdefault(store_key, []).append(audit)

    return SendOut(
        sent=bool(result.get("sent")),
        reason=result.get("reason"),
        detail=result.get("detail") or result.get("message_id"),
        channel=channel,
    )
