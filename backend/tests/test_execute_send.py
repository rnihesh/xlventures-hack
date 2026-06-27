"""Offline tests for the multi-recipient send path of ``POST /execute/send``.

An email artifact can fan out to several people at once: any number of saved
contacts plus any number of raw addresses. These tests prove the send reaches
each recipient and returns a per-recipient breakdown, that single-recipient
calls still work (backward compatibility), and that everything degrades to
``ses_not_configured`` offline rather than raising. The suite runs with no AWS
credentials (see conftest), so every SES send takes its not-configured path.
"""

from __future__ import annotations


def _make_run_with_recommendation(client) -> str:
    """Create a run and drive the offline graph so a recommendation is stored."""

    payload = {
        "domain": "customer_success",
        "account_id": "ACC-1001",
        "signal": {
            "type": "usage_drop",
            "content": "Usage down 38% QoQ; sponsor disengaged ahead of renewal",
        },
    }
    run_id = client.post("/runs", json=payload).json()["run_id"]
    assert client.get(f"/runs/{run_id}/stream").status_code == 200
    return run_id


def _make_contact(client, name: str, email: str) -> str:
    resp = client.post("/contacts", json={"name": name, "email": email})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_send_to_multiple_recipients_offline(client) -> None:
    """Contacts plus raw addresses fan out, each with its own result."""

    run_id = _make_run_with_recommendation(client)
    a = _make_contact(client, "Dana Lee", "dana@acme.com")
    b = _make_contact(client, "Sam Ray", "sam@acme.com")

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "email",
            "run_id": run_id,
            "account_id": "ACC-1001",
            "artifact": {"subject": "Renewal plan", "body": "Let us talk."},
            "contact_ids": [a, b],
            "recipients": ["ops@acme.com"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Offline: SES is not configured, so the combined send did not go through and
    # carries the per-recipient breakdown for all three addresses.
    assert body["sent"] is False
    assert body["reason"] == "ses_not_configured"
    assert body["channel"] == "email"

    results = body["results"]
    assert isinstance(results, list) and len(results) == 3
    addressed = {r["to"] for r in results}
    assert addressed == {"dana@acme.com", "sam@acme.com", "ops@acme.com"}
    assert all(r["sent"] is False for r in results)
    assert all(r["reason"] == "ses_not_configured" for r in results)

    # The combined `to` line lists every recipient we tried.
    for addr in ("dana@acme.com", "sam@acme.com", "ops@acme.com"):
        assert addr in (body["to"] or "")


def test_send_single_recipient_still_works(client) -> None:
    """The legacy single ``to`` field is honored and yields one result row."""

    run_id = _make_run_with_recommendation(client)

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "email",
            "run_id": run_id,
            "account_id": "ACC-1001",
            "artifact": {"subject": "Hi", "body": "Body"},
            "to": "single@acme.com",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False
    assert body["reason"] == "ses_not_configured"
    assert body["results"] == [
        {
            "to": "single@acme.com",
            "sent": False,
            "reason": "ses_not_configured",
            "detail": None,
        }
    ]


def test_send_dedupes_repeated_recipients(client) -> None:
    """The same address via a contact and a raw entry is sent to once."""

    run_id = _make_run_with_recommendation(client)
    a = _make_contact(client, "Dana Lee", "dana@acme.com")

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "email",
            "run_id": run_id,
            "account_id": "ACC-1001",
            "artifact": {"subject": "Hi", "body": "Body"},
            "contact_ids": [a],
            "recipients": ["DANA@acme.com", "ops@acme.com"],
        },
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert len(results) == 2
    assert {r["to"] for r in results} == {"dana@acme.com", "ops@acme.com"}


def test_send_unknown_contact_is_not_found(client) -> None:
    """A contact_id that does not exist in the org returns contact_not_found."""

    run_id = _make_run_with_recommendation(client)

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "email",
            "run_id": run_id,
            "artifact": {"subject": "Hi", "body": "Body"},
            "contact_ids": ["con_does_not_exist"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False
    assert body["reason"] == "contact_not_found"
