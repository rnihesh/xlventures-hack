"""Account 360 "Documents and evidence": real ingested docs, org-scoped (offline).

A user who uploaded crm-notes / a call transcript / an email thread for their
account must see all of them under the account's documents, and one org must
never see another org's ingested evidence (even when both reference the same
account id).
"""

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


def _ingest(tc: TestClient, account_id: str, source_type: str, title: str, text: str):
    resp = tc.post(
        "/ingest",
        json={
            "text": text,
            "source_type": source_type,
            "title": title,
            "account_id": account_id,
            "domain": "customer_success",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_uploaded_documents_appear_in_account_detail(app) -> None:
    """All three uploaded interactions show up under the account's documents."""

    a = _fresh_org_client(app)
    acc_id = a.post("/accounts", json={"name": "Halcyon Fitness"}).json()["account_id"]

    _ingest(
        a,
        acc_id,
        "crm_record",
        "crm-notes",
        "Halcyon Fitness exec sponsor departed last week; renewal now at risk.",
    )
    _ingest(
        a,
        acc_id,
        "call_transcript",
        "call-transcript",
        "On the call the champion said adoption stalled across the data import flow.",
    )
    _ingest(
        a,
        acc_id,
        "email",
        "email-thread",
        "Email thread: procurement asked about pricing before they will renew.",
    )

    detail = a.get(f"/accounts/{acc_id}").json()
    docs = detail["documents"]
    titles = {d["title"] for d in docs}
    assert {"crm-notes", "call-transcript", "email-thread"} <= titles

    # The excerpt carries the original interaction text (not just a label).
    crm = next(d for d in docs if d["title"] == "crm-notes")
    assert "exec sponsor departed" in (crm["excerpt"] or "")
    assert crm["source_type"] == "crm_record"


def test_documents_are_org_scoped(app) -> None:
    """Org B never sees org A's ingested documents, even for a shared account id."""

    a = _fresh_org_client(app)
    b = _fresh_org_client(app)

    # Both orgs adopt the shared demo account ids so the account id alone cannot
    # explain any isolation: the org boundary must.
    assert a.post("/accounts/import-demo").status_code == 200
    assert b.post("/accounts/import-demo").status_code == 200

    _ingest(
        a,
        "ACC-1001",
        "crm_record",
        "A-only CRM note",
        "Private to org A: renewal blocker flagged on pricing during the QBR.",
    )

    da = a.get("/accounts/ACC-1001").json()
    assert "A-only CRM note" in {d["title"] for d in da["documents"]}

    db = b.get("/accounts/ACC-1001").json()
    assert "A-only CRM note" not in {d["title"] for d in db["documents"]}
    # A fresh non-demo org sees no seed corpus either: honest-empty documents.
    assert db["documents"] == []
