"""Contacts CRUD (org-scoped) and contact-resolved email send (offline)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _fresh_org_client(app) -> TestClient:
    """Sign up a brand-new org and return a logged-in client for it."""

    email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    tc = TestClient(app)
    signup = tc.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "secret123",
            "name": "New User",
            "org_name": f"Org {uuid.uuid4().hex[:6]}",
        },
    )
    assert signup.status_code == 201, signup.text
    login = tc.post("/auth/login", json={"email": email, "password": "secret123"})
    assert login.status_code == 200, login.text
    return tc


def test_contact_crud_and_listing(client) -> None:
    """A contact can be created, listed, updated, and deleted in the org."""

    resp = client.post(
        "/contacts",
        json={
            "name": "Dana Lee",
            "email": "dana@acme.com",
            "role": "Economic buyer",
        },
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    contact_id = created["id"]
    assert contact_id.startswith("con_")
    assert created["name"] == "Dana Lee"
    assert created["email"] == "dana@acme.com"

    listing = client.get("/contacts")
    assert listing.status_code == 200
    ids = {c["id"] for c in listing.json()}
    assert contact_id in ids

    upd = client.put(f"/contacts/{contact_id}", json={"role": "Champion"})
    assert upd.status_code == 200
    assert upd.json()["role"] == "Champion"
    # Unset fields are preserved across a partial update.
    assert upd.json()["email"] == "dana@acme.com"

    deleted = client.delete(f"/contacts/{contact_id}")
    assert deleted.status_code == 200
    assert client.delete(f"/contacts/{contact_id}").status_code == 404


def test_account_scoped_contacts(client) -> None:
    """A contact linked to an account shows up under that account."""

    c = client.post(
        "/contacts",
        json={"name": "Sam Roe", "email": "sam@northwind.com", "account_id": "ACC-1001"},
    ).json()

    linked = client.get("/accounts/ACC-1001/contacts")
    assert linked.status_code == 200
    assert c["id"] in {x["id"] for x in linked.json()}

    other = client.get("/accounts/ACC-9999/contacts")
    assert other.status_code == 200
    assert c["id"] not in {x["id"] for x in other.json()}


def test_contacts_org_isolated(app, client) -> None:
    """One org never sees another org's contacts."""

    other = _fresh_org_client(app)
    mine = client.post(
        "/contacts", json={"name": "Private Pat", "email": "pat@mine.com"}
    ).json()

    other_ids = {c["id"] for c in other.get("/contacts").json()}
    assert mine["id"] not in other_ids


def test_send_resolves_recipient_from_contact_id(client, monkeypatch) -> None:
    """POST /execute/send with a contact_id sends to that contact's email."""

    contact = client.post(
        "/contacts", json={"name": "Ren Vox", "email": "ren@buyer.io"}
    ).json()

    captured: dict[str, str] = {}

    def _fake_send_email(*, to, subject, body, sender):  # noqa: ANN001
        captured["to"] = to
        return {"sent": True, "message_id": "fake-123"}

    from app.api import execute as execute_api

    monkeypatch.setattr(execute_api.email_service, "send_email", _fake_send_email)

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "email",
            "artifact": {"subject": "Hi", "body": "Body"},
            "contact_id": contact["id"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] is True
    assert captured["to"] == "ren@buyer.io"


def test_send_unknown_contact_id_reports_not_found(client) -> None:
    """An unknown contact_id yields a graceful not-found result, not a crash."""

    resp = client.post(
        "/execute/send",
        json={
            "artifact_type": "email",
            "artifact": {"subject": "Hi", "body": "Body"},
            "contact_id": "con_doesnotexist",
        },
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["sent"] is False
    assert out["reason"] == "contact_not_found"
