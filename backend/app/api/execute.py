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
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.actions import ARTIFACT_TYPES, generate_artifact
from app.actions.generators import _llm_available
from app.api._org import current_org
from app.config import settings
from app.repositories import connectors as connectors_repo
from app.repositories import contacts as contacts_repo
from app.services import email as email_service
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
    # Email recipient resolution. An email can fan out to several people: any
    # number of saved contacts (``contact_ids``) plus any number of raw
    # addresses (``recipients``). The singular ``contact_id`` / ``to`` fields are
    # kept for backward compatibility and folded into those lists. When nothing
    # is supplied the artifact / account fallback is used, exactly as before.
    contact_id: Optional[str] = None
    to: Optional[str] = None
    contact_ids: Optional[List[str]] = None
    recipients: Optional[List[str]] = None


class SendOut(BaseModel):
    sent: bool
    reason: Optional[str] = None
    detail: Optional[Any] = None
    channel: Optional[str] = None
    # Where it went: a single recipient, or a comma-joined list for a fan-out.
    to: Optional[str] = None
    # Per-recipient breakdown for a multi-recipient email send (one entry per
    # address with its own ``sent`` / ``reason``). Absent for single sends and
    # for non-email channels.
    results: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Context resolution (best-effort, tolerant of missing slices)
# ---------------------------------------------------------------------------


def _lookup_run(run_id: str, org_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch a run record from the runs slice, if that slice is loaded.

    When ``org_id`` is provided, ownership is enforced: a run owned by a
    different org is treated as not found so a caller can never resolve another
    tenant's recommendation (or its originating signal) through this slice.
    """

    try:
        from app.api.runs import _RUNS
    except Exception:  # noqa: BLE001 - runs slice optional
        return None
    run = _RUNS.get(run_id)
    if run is None:
        return None
    if org_id is not None and run.get("org_id") != org_id:
        return None
    return run


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


def _resolve_recommendation_from(
    recommendation: Optional[Dict[str, Any]],
    run_id: Optional[str],
    account_id: Optional[str],
    org_id: Optional[str] = None,
) -> tuple[Dict[str, Any], Optional[str], Optional[Dict[str, Any]]]:
    """Resolve a recommendation plus account context and the backing run.

    Accepts an inline ``recommendation`` or a ``run_id`` whose stored
    recommendation is pulled from the runs slice. Returns the recommendation,
    the resolved account id, and the run record (or None when inline / absent)
    so callers that want the originating signal can read it. When ``org_id`` is
    given, a ``run_id`` is resolved only if that run belongs to the caller's org
    (cross-org runs are treated as absent).
    """

    rec: Optional[Dict[str, Any]] = recommendation
    run: Optional[Dict[str, Any]] = None

    if rec is None and run_id:
        run = _lookup_run(run_id, org_id)
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
    return rec, account_id, run


def _resolve_recommendation(
    body: ExecuteIn, org_id: Optional[str] = None
) -> tuple[Dict[str, Any], Optional[str]]:
    """Return the recommendation to act on plus the resolved account id.

    When ``org_id`` is given a ``run_id`` is resolved only if that run belongs to
    the caller's org, so a recommendation (or its signal) can never be pulled
    across the tenant boundary.
    """

    rec, account_id, _run = _resolve_recommendation_from(
        body.recommendation, body.run_id, body.account_id, org_id=org_id
    )
    return rec, account_id


def _run_owner(run_id: Optional[str]) -> Optional[str]:
    """Return the org that owns a stored run, or None when unknown / legacy.

    Used to reject (404) a cross-org ``run_id`` before any artifact is generated
    or read. A run_id that is not in the registry (e.g. a client-supplied id used
    with an inline recommendation) has no owner and is left to the normal flow.
    """

    if not run_id:
        return None
    try:
        from app.api.runs import _RUNS
    except Exception:  # noqa: BLE001 - runs slice optional
        return None
    run = _RUNS.get(run_id)
    if run is None:
        return None
    return run.get("org_id")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/execute", response_model=ExecuteOut)
async def execute(
    body: ExecuteIn, org_id: str = Depends(current_org)
) -> ExecuteOut:
    """Generate an artifact from a recommendation and record an audit entry.

    Org-scoped: a ``run_id`` that names another tenant's run returns 404 (never
    403, to avoid an id-enumeration oracle) and nothing is generated or stored.
    Same-org runs and inline recommendations behave exactly as before. The audit
    record is stamped with the caller's org so reads can be gated by tenant.
    """

    if body.artifact_type not in ARTIFACT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid artifact_type; expected one of {list(ARTIFACT_TYPES)}",
        )

    owner = _run_owner(body.run_id)
    if owner is not None and owner != org_id:
        raise HTTPException(status_code=404, detail="run not found")

    rec, account_id = _resolve_recommendation(body, org_id)
    account = _lookup_account(account_id)

    # Enrich with the caller's real org account so customer-facing copy uses the
    # account NAME (e.g. "Halcyon Fitness"), never the internal id. The seed
    # _lookup_account above does not know an org's own accounts.
    try:
        from app.api.accounts import _org_account

        org_acct = await _org_account(org_id, account_id) if account_id else None
        if org_acct:
            account = {**(account or {}), **org_acct}
    except Exception:  # noqa: BLE001 - name enrichment is best effort
        pass

    try:
        artifact = generate_artifact(body.artifact_type, rec, account)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    action = rec.get("action") if isinstance(rec.get("action"), dict) else {}
    audit: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "run_id": body.run_id,
        "org_id": org_id,
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
async def list_artifacts(
    run_id: str, org_id: str = Depends(current_org)
) -> List[Dict[str, Any]]:
    """List artifacts generated for a run, most recent first, scoped to the org.

    Reads are gated by tenant: a ``run_id`` owned by (or whose stored artifacts
    belong to) another org returns 404 instead of leaking those records or
    revealing they exist. An own run with no artifacts yet still returns an empty
    list, preserving the existing success behavior.
    """

    owner = _run_owner(run_id)
    if owner is not None and owner != org_id:
        raise HTTPException(status_code=404, detail="run not found")

    records = _ARTIFACTS.get(run_id, [])
    # Legacy records (no org stamp) are treated as the caller's; anything stamped
    # with a different org is foreign and must not be returned.
    owned = [r for r in records if r.get("org_id") in (None, org_id)]
    foreign = [r for r in records if r.get("org_id") not in (None, org_id)]
    if foreign and not owned:
        raise HTTPException(status_code=404, detail="run not found")
    return list(reversed(owned))


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


def _dedupe_preserving(addresses: List[str]) -> List[str]:
    """Drop blanks and case-insensitive duplicates, keeping first-seen order."""

    seen: set[str] = set()
    out: List[str] = []
    for addr in addresses:
        clean = (addr or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


async def _resolve_email_recipients(
    body: "SendIn",
    org_id: str,
    artifact: Dict[str, Any],
    account: Dict[str, Any],
) -> tuple[List[str], Optional[str]]:
    """Resolve every email recipient for a send.

    Combines saved contacts (``contact_ids`` plus the singular ``contact_id``)
    with raw addresses (``recipients`` plus the singular ``to``). Falls back to
    the artifact / account contact when nothing explicit is given. Returns the
    deduped address list and, when a referenced contact does not exist in the
    org, that missing contact id (so the caller can answer ``contact_not_found``)
    with an empty list.
    """

    addresses: List[str] = []

    contact_ids = list(body.contact_ids or [])
    if body.contact_id:
        contact_ids.append(body.contact_id)
    for cid in _dedupe_preserving(contact_ids):
        contact = await contacts_repo.get(org_id, cid)
        if contact is None:
            return [], cid
        if contact.get("email"):
            addresses.append(str(contact["email"]))

    raw = list(body.recipients or [])
    if body.to:
        raw.append(body.to)
    addresses.extend(raw)

    resolved = _dedupe_preserving(addresses)
    if not resolved:
        fallback = _recipient_email(artifact, account)
        if fallback:
            resolved = [fallback]
    return resolved, None


def _slack_text(artifact: Dict[str, Any]) -> str:
    """Resolve the message text from a slack (or generic) artifact."""

    return str(
        artifact.get("message")
        or artifact.get("text")
        or artifact.get("body")
        or ""
    )


# ---------------------------------------------------------------------------
# Slack HITL approval handoff
# ---------------------------------------------------------------------------


class ApprovalHandoffIn(BaseModel):
    """Body for POST /execute/approval-handoff.

    Provide either a ``run_id`` (to pull the stored recommendation and its
    originating signal) or an inline ``recommendation``. ``account_id`` supplies
    account context; when a ``run_id`` is given its account is used as a
    fallback. The endpoint posts a rich, sign-off-ready summary to the org's
    Slack channel so a human can approve the pending action.
    """

    run_id: Optional[str] = None
    recommendation: Optional[Dict[str, Any]] = None
    account_id: Optional[str] = None


def _account_name(account: Dict[str, Any], account_id: Optional[str]) -> str:
    """Best-effort human label for the account in the Slack message."""

    if isinstance(account, dict):
        if account.get("name"):
            return str(account["name"])
        profile = account.get("profile")
        if isinstance(profile, dict) and profile.get("name"):
            return str(profile["name"])
        if account.get("account_id"):
            return str(account["account_id"])
    return account_id or "the account"


def _signal_oneliner(signal: Optional[Dict[str, Any]], fallback: str) -> str:
    """Render the originating signal as a one-line context string."""

    if isinstance(signal, dict):
        kind = str(signal.get("type") or "").strip()
        content = str(signal.get("content") or "").strip()
        if kind and content:
            return f"{kind}: {content}"
        if content:
            return content
        if kind:
            return kind
    return fallback


def _top_alternative(rec: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Pick the best runner-up (the first non-chosen alternative with a title)."""

    alternatives = rec.get("alternatives")
    if not isinstance(alternatives, list):
        return None, None
    for alt in alternatives:
        if not isinstance(alt, dict) or alt.get("chosen"):
            continue
        action = alt.get("action") if isinstance(alt.get("action"), dict) else {}
        title = action.get("title") or alt.get("title")
        if title:
            why = alt.get("why_not")
            return str(title), str(why) if why else None
    return None, None


def _approval_message(
    rec: Dict[str, Any],
    account: Dict[str, Any],
    account_id: Optional[str],
    signal: Optional[Dict[str, Any]],
) -> str:
    """Build a rich Slack mrkdwn approval message for a pending recommendation."""

    action = rec.get("action") if isinstance(rec.get("action"), dict) else {}
    title = action.get("title") or "the recommended next step"
    description = str(action.get("description") or "").strip()
    rationale = str(rec.get("rationale") or "").strip()

    confidence = rec.get("confidence") if isinstance(rec.get("confidence"), dict) else {}
    score = confidence.get("score")
    label = str(confidence.get("label") or "unknown")
    conf_line = label
    if isinstance(score, (int, float)):
        conf_line = f"{round(float(score) * 100)}% ({label})"

    risk = rec.get("risk_opportunity") if isinstance(rec.get("risk_opportunity"), dict) else {}
    summary = str(risk.get("summary") or "").strip()

    name = _account_name(account, account_id)
    context = _signal_oneliner(signal, summary)
    alt_title, alt_why = _top_alternative(rec)

    lines = [
        ":rotating_light: *Approval needed in Aperture*",
        f"*Account:* {name}",
    ]
    if context:
        lines.append(f"*Signal:* {context}")
    lines.append(f"*Recommended next best action:* {title}")
    if description:
        lines.append(f"> {description}")
    if rationale:
        lines.append(f"*Why:* {rationale}")
    lines.append(f"*Confidence:* {conf_line}")
    if alt_title:
        alt_line = f"*Top alternative considered:* {alt_title}"
        if alt_why:
            alt_line += f" (not chosen: {alt_why})"
        lines.append(alt_line)
    lines.append(
        "This recommendation is *pending human approval*. "
        "Approve, edit, or decline it in Aperture."
    )
    return "\n".join(lines)


@router.post("/execute/approval-handoff", response_model=SendOut)
async def execute_approval_handoff(
    body: ApprovalHandoffIn,
    org_id: str = Depends(current_org),
) -> SendOut:
    """Push a pending recommendation to the org's Slack channel for sign-off.

    Posts a rich approval summary (account, signal, recommended next best action
    plus reasoning, confidence, top alternative, and that it is pending human
    approval) to the org's saved Slack webhook. Offline-safe and org-scoped:
    when no webhook is configured it returns ``{sent: False, reason:
    'slack_not_configured'}`` rather than raising.
    """

    # Org-scoped: a cross-org run is treated as absent (org_id is threaded into
    # resolution), so its recommendation and signal can never be pushed into this
    # caller's Slack channel. An unresolvable run yields 422, never a leak.
    rec, account_id, run = _resolve_recommendation_from(
        body.recommendation, body.run_id, body.account_id, org_id=org_id
    )
    account = _lookup_account(account_id)
    signal = run.get("signal") if isinstance(run, dict) else None
    text = _approval_message(rec, account, account_id, signal)

    connector = await connectors_repo.get(org_id, "slack")
    config = (connector or {}).get("config") or {}
    # post_message uses a synchronous HTTP client; run it off the event loop so
    # a slow Slack webhook cannot block other requests. The no-webhook path
    # returns immediately (no network), keeping the offline case cheap.
    result = await run_in_threadpool(
        slack_service.post_message, config.get("webhook_url"), text
    )

    audit: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "run_id": body.run_id,
        "org_id": org_id,
        "account_id": account_id,
        "channel": "slack",
        "action": "approval_handoff",
        "recommendation_id": rec.get("id"),
        "sent": bool(result.get("sent")),
        "reason": result.get("reason"),
        "created_at": _now_iso(),
    }
    store_key = body.run_id or _UNATTACHED_KEY
    _ARTIFACTS.setdefault(store_key, []).append(audit)

    return SendOut(
        sent=bool(result.get("sent")),
        reason=result.get("reason"),
        detail=result.get("detail"),
        channel="slack",
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
    to_line: Optional[str] = None
    results_list: Optional[List[Dict[str, Any]]] = None

    if kind in ("email", "gmail", "google"):
        # All email sends go over SES from the single platform sender. There is
        # no per-org sender configuration; Google is a sign-in method, not a mail
        # connector. An email can fan out to several people: resolve every saved
        # contact and raw address (plus the artifact / account fallback) and send
        # to each, returning a per-recipient breakdown.
        recipients, missing_contact = await _resolve_email_recipients(
            body, org_id, artifact, account
        )
        if missing_contact is not None:
            return SendOut(sent=False, reason="contact_not_found", channel="email")
        if not recipients:
            result = {"sent": False, "reason": "no_recipient"}
        else:
            subject = str(artifact.get("subject") or "(no subject)")
            email_body = str(artifact.get("body") or "")
            per: List[Dict[str, Any]] = []
            for addr in recipients:
                # send_email is a synchronous boto3/SES call; run it off the event
                # loop so a slow SES round-trip cannot block other requests (the
                # offline / no-creds path returns before any network).
                one = await run_in_threadpool(
                    email_service.send_email,
                    to=addr,
                    subject=subject,
                    body=email_body,
                    sender=settings.ses_sender_email,
                )
                per.append(
                    {
                        "to": addr,
                        "sent": bool(one.get("sent")),
                        "reason": one.get("reason"),
                        "detail": one.get("detail") or one.get("message_id"),
                    }
                )
            sent_any = any(p["sent"] for p in per)
            # The send succeeds when at least one address was delivered; the
            # combined reason is the first failure (all share it offline).
            result = {
                "sent": sent_any,
                "reason": None
                if sent_any
                else next((p["reason"] for p in per if p["reason"]), None),
            }
            to_line = ", ".join(p["to"] for p in per if p["sent"]) or ", ".join(
                p["to"] for p in per
            )
            results_list = per
        channel = "email"

    elif kind == "slack":
        connector = await connectors_repo.get(org_id, "slack")
        config = (connector or {}).get("config") or {}
        # Off the event loop: post_message is a synchronous HTTP call.
        result = await run_in_threadpool(
            slack_service.post_message, config.get("webhook_url"), _slack_text(artifact)
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
        "org_id": org_id,
        "account_id": body.account_id,
        "channel": channel,
        "action": "send",
        "sent": bool(result.get("sent")),
        "reason": result.get("reason"),
        "to": to_line,
        "recipients": [p["to"] for p in results_list] if results_list else None,
        "created_at": _now_iso(),
    }
    store_key = body.run_id or _UNATTACHED_KEY
    _ARTIFACTS.setdefault(store_key, []).append(audit)

    return SendOut(
        sent=bool(result.get("sent")),
        reason=result.get("reason"),
        detail=result.get("detail") or result.get("message_id"),
        channel=channel,
        to=to_line,
        results=results_list,
    )
