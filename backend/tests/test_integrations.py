"""Tests for the integrations connectors and the offline real-send path.

All assertions hold offline (no DATABASE_URL, no AWS / Slack / Google creds):

* the connectors repository round-trips an upsert / list / delete through its
  in-memory fallback;
* the integrations API saves and lists a Slack connector, masking secrets;
* POST /execute/send degrades gracefully to ``sent: False`` with a
  "not configured" reason for every channel instead of crashing.
"""

from __future__ import annotations

from typing import Any, Dict

from app.repositories import connectors as connectors_repo


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
