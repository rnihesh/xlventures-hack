"""Tests for the integrations connectors and the offline real-send path.

All assertions hold offline (no DATABASE_URL, no AWS / Slack / Google creds):

* the connectors repository round-trips an upsert / list / delete through its
  in-memory fallback;
* the integrations API saves and lists a Slack connector, masking secrets;
* POST /execute/send degrades gracefully to ``sent: False`` with a
  "not configured" reason for every channel instead of crashing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.repositories import connectors as connectors_repo
from app.services import slack as slack_service

# A rich, pending recommendation used to exercise the Slack approval handoff.
_PENDING_REC: Dict[str, Any] = {
    "id": "rec_handoff_1",
    "account_id": "acc_demo",
    "action": {
        "key": "schedule_ebr",
        "title": "Schedule an executive business review",
        "description": "Re-engage the sponsor before renewal.",
    },
    "rationale": "Usage fell sharply and the sponsor went quiet ahead of renewal.",
    "confidence": {"score": 0.72, "label": "high", "method": "ensemble"},
    "risk_opportunity": {
        "type": "risk",
        "summary": "Churn risk: usage down 32% with renewal in 45 days.",
    },
    "alternatives": [
        {
            "action": {"key": "schedule_ebr", "title": "Schedule an executive business review"},
            "score": 0.72,
            "why_not": None,
            "chosen": True,
        },
        {
            "action": {"key": "reonboard_email", "title": "Send a re-onboarding email"},
            "score": 0.4,
            "why_not": "Lower expected impact than a live review.",
        },
    ],
}


async def test_connectors_upsert_list_delete() -> None:
    """The repository round-trips a connector through the offline store."""

    org = "org_test_connectors"
    # Clean slate (offline store is process-local).
    await connectors_repo.delete(org, "slack")

    saved = await connectors_repo.upsert(
        org, "slack", {"webhook_url": "https://hooks.slack.test/abc"}, status="connected"
    )
    assert saved["kind"] == "slack"
    assert saved["status"] == "connected"
    assert saved["config"]["webhook_url"] == "https://hooks.slack.test/abc"

    fetched = await connectors_repo.get(org, "slack")
    assert fetched is not None and fetched["config"]["webhook_url"].endswith("abc")

    listed = await connectors_repo.list(org)
    assert any(c["kind"] == "slack" for c in listed)

    # Scoping: another org sees none of this org's connectors.
    assert await connectors_repo.list("org_other_tenant") == []

    assert await connectors_repo.delete(org, "slack") is True
    assert await connectors_repo.get(org, "slack") is None


def test_integrations_save_and_list(client) -> None:
    """PUT then GET /integrations returns the connector with secrets masked."""

    resp = client.put(
        "/integrations/slack",
        json={"config": {"webhook_url": "https://hooks.slack.test/demo"}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "connected"

    listing = client.get("/integrations")
    assert listing.status_code == 200
    body: Dict[str, Any] = listing.json()
    assert "google_oauth_configured" in body
    kinds = {c["kind"] for c in body["connectors"]}
    assert "slack" in kinds


def test_integrations_invalid_kind(client) -> None:
    """An unknown connector kind is rejected with 422."""

    resp = client.put("/integrations/telegram", json={"config": {}})
    assert resp.status_code == 422


def test_integrations_google_start_offline(client) -> None:
    """Google start reports not-configured offline rather than crashing."""

    resp = client.get("/integrations/google/start")
    assert resp.status_code == 200
    body = resp.json()
    # Offline: no GOOGLE_CLIENT_ID, so the flow is not configured but does not crash.
    assert body["configured"] is False
    assert body["url"] is None


def test_execute_send_email_offline(client) -> None:
    """Sending an email offline returns sent=False with a graceful reason."""

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "email",
            "artifact": {
                "to": "ops@acme.test",
                "subject": "Hello",
                "body": "Quick check-in.",
            },
            "account_id": "acc_demo",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False
    assert body["channel"] == "email"
    assert body["reason"]  # a non-empty "not configured" style reason


def test_execute_send_slack_offline(client) -> None:
    """Sending to Slack with no configured webhook returns sent=False."""

    # Ensure the demo org has no slack webhook so we exercise the unconfigured
    # path deterministically (other tests may have saved one in the shared store).
    client.delete("/integrations/slack")

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "slack",
            "artifact": {"message": "Handoff: Acme"},
            "account_id": "acc_demo",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False
    assert body["reason"] == "slack_not_configured"


def test_execute_send_gmail_routes_to_ses(client) -> None:
    """The gmail/google artifact type now sends over SES (Google is sign-in only),
    so with SES unconfigured offline it returns sent=False, ses_not_configured."""

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "gmail",
            "artifact": {
                "to": "ops@acme.test",
                "subject": "Hello",
                "body": "Quick check-in.",
            },
            "account_id": "acc_demo",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False
    assert body["reason"] == "ses_not_configured"


def test_execute_send_invalid_channel(client) -> None:
    """An unsupported channel is rejected with 422."""

    resp = client.post(
        "/execute/send",
        json={"artifact_type": "carrier_pigeon", "artifact": {}},
    )
    assert resp.status_code == 422


def test_approval_handoff_not_configured(client) -> None:
    """With no Slack webhook saved, the handoff degrades to sent=False."""

    # Ensure the demo org has no slack webhook so we hit the unconfigured path.
    client.delete("/integrations/slack")

    resp = client.post(
        "/execute/approval-handoff",
        json={"recommendation": _PENDING_REC, "account_id": "acc_demo"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False
    assert body["reason"] == "slack_not_configured"
    assert body["channel"] == "slack"


def test_approval_handoff_posts_when_configured(client, monkeypatch) -> None:
    """A saved webhook makes the handoff post a rich, org-scoped approval message."""

    # A different tenant's webhook must never be used for this org's handoff.
    asyncio.run(
        connectors_repo.upsert(
            "org_other_tenant", "slack", {"webhook_url": "https://hooks.slack.test/other"}
        )
    )

    captured: Dict[str, Any] = {}

    def fake_post(webhook_url: str | None, text: str) -> Dict[str, Any]:
        captured["webhook_url"] = webhook_url
        captured["text"] = text
        return {"sent": True}

    # Patch the module attribute the endpoint resolves at call time (no network).
    monkeypatch.setattr(slack_service, "post_message", fake_post)

    saved = client.put(
        "/integrations/slack",
        json={"config": {"webhook_url": "https://hooks.slack.test/demo"}},
    )
    assert saved.status_code == 200, saved.text

    resp = client.post(
        "/execute/approval-handoff",
        json={"recommendation": _PENDING_REC, "account_id": "acc_demo"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is True
    assert body["channel"] == "slack"

    # Org-scoped: it used the demo org's webhook, not the other tenant's.
    assert captured["webhook_url"] == "https://hooks.slack.test/demo"

    # The message is rich and flags the pending-approval state.
    text = captured["text"]
    assert "pending human approval" in text.lower()
    assert "Schedule an executive business review" in text
    assert "Send a re-onboarding email" in text  # top alternative
    assert "72%" in text  # confidence score

    client.delete("/integrations/slack")


def test_approval_handoff_requires_recommendation(client) -> None:
    """Without a recommendation or resolvable run, the handoff is rejected 422."""

    resp = client.post("/execute/approval-handoff", json={"account_id": "acc_demo"})
    assert resp.status_code == 422


def test_approval_handoff_does_not_read_other_orgs_run(client, monkeypatch) -> None:
    """A run owned by another org must not be resolvable through the handoff.

    Pushing another tenant's recommendation (and its signal) into the caller's
    Slack channel would be a cross-org leak, so the run is treated as absent and
    the request is rejected 422 rather than posting anything.
    """

    from app.api.runs import _RUNS

    run_id = "run_other_org_secret"
    _RUNS[run_id] = {
        "run_id": run_id,
        "org_id": "org_other_tenant",
        "domain": "customer_success",
        "account_id": "acc_secret",
        "signal": {"type": "email", "content": "confidential churn signal"},
        "recommendation": _PENDING_REC,
    }

    posted: Dict[str, Any] = {}

    def fake_post(webhook_url: str | None, text: str) -> Dict[str, Any]:
        posted["text"] = text
        return {"sent": True}

    monkeypatch.setattr(slack_service, "post_message", fake_post)
    try:
        resp = client.post(
            "/execute/approval-handoff",
            json={"run_id": run_id},
        )
        assert resp.status_code == 422
        # Nothing from the other org's run was ever posted.
        assert "text" not in posted
    finally:
        _RUNS.pop(run_id, None)
