"""Account creation, demo import, and org isolation (offline)."""

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


def test_create_account_then_listed(client) -> None:
    """A created account appears in that org's inbox."""

    resp = client.post(
        "/accounts",
        json={
            "name": "Acme Robotics",
            "domain": "customer_success",
            "arr": 120000,
            "risk_level": "high",
            "health_score": 42,
            "signals": ["support_ticket_spike", {"key": "usage_drop", "label": "Usage drop"}],
            "notes": "Renewal at risk after a rough onboarding.",
        },
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    account_id = created["account_id"]
    assert account_id.startswith("ACC-")
    assert created["name"] == "Acme Robotics"
    assert created["risk_level"] == "high"

    listing = client.get("/accounts")
    assert listing.status_code == 200
    ids = {a["account_id"] for a in listing.json()}
    assert account_id in ids

    detail = client.get(f"/accounts/{account_id}")
    assert detail.status_code == 200
    assert detail.json()["profile"]["account_id"] == account_id


def test_update_and_delete_account(client) -> None:
    """An account can be updated then removed from the org."""

    created = client.post("/accounts", json={"name": "Temp Co"}).json()
    account_id = created["account_id"]

    upd = client.put(f"/accounts/{account_id}", json={"risk_level": "critical", "arr": 99})
    assert upd.status_code == 200
    assert upd.json()["risk_level"] == "critical"

    deleted = client.delete(f"/accounts/{account_id}")
    assert deleted.status_code == 200

    assert client.get(f"/accounts/{account_id}").status_code == 404
    assert client.delete(f"/accounts/{account_id}").status_code == 404


def test_import_demo_populates_and_isolated(app, client) -> None:
    """import-demo fills a fresh org; another org never sees its accounts."""

    other = _fresh_org_client(app)

    # Fresh org starts empty.
    assert other.get("/accounts").json() == []

    imp = other.post("/accounts/import-demo")
    assert imp.status_code == 200
    imported = imp.json()["imported"]
    assert imported >= 3
    assert len(other.get("/accounts").json()) == imported

    # Idempotent: re-import does not change the count.
    again = other.post("/accounts/import-demo")
    assert again.json()["imported"] == imported

    # Isolation: an account created in the other org is invisible to demo.
    new_acc = other.post("/accounts", json={"name": "Isolated Inc"}).json()
    demo_ids = {a["account_id"] for a in client.get("/accounts").json()}
    assert new_acc["account_id"] not in demo_ids
    other_ids = {a["account_id"] for a in other.get("/accounts").json()}
    assert new_acc["account_id"] in other_ids
