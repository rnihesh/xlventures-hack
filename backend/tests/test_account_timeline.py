"""Account 360 timeline endpoint: shape, merge, ordering, and org-scoping (offline)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from app.api._org import DEMO_ORG


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


def test_timeline_shape_for_seed_account(client) -> None:
    """A seeded demo account returns a well-shaped, interaction-bearing timeline."""

    resp = client.get("/accounts/ACC-1001/timeline")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["account_id"] == "ACC-1001"
    assert "name" in body
    assert isinstance(body["events"], list)
    counts = body["counts"]
    for key in ("interaction", "recommendation", "decision", "outcome", "total"):
        assert key in counts

    # Seed documents surface as interaction events (org owns the seed corpus).
    assert counts["interaction"] >= 1
    interactions = [e for e in body["events"] if e["kind"] == "interaction"]
    assert interactions
    sample = interactions[0]
    assert "title" in sample and "source_type" in sample and "kind" in sample

    # Every event carries the common timeline fields.
    for ev in body["events"]:
        assert ev["kind"] in {"interaction", "recommendation", "decision", "outcome"}
        assert "id" in ev and "title" in ev and "ts" in ev


def test_timeline_merges_run_decision_outcome_newest_first(client) -> None:
    """A run + human decision + outcome appear, ordered newest first."""

    from app.memory.store import get_memory

    account_id = "ACC-1002"
    memory = get_memory()

    async def _seed_episode() -> str:
        ep_id = await memory.write_episode(
            account_id=account_id,
            domain="customer_success",
            situation="Renewal at risk after a rough quarter.",
            action_key="schedule_exec_review",
            recommendation={
                "action": {"key": "schedule_exec_review", "title": "Schedule exec review"},
                "confidence": {"score": 0.82, "label": "high", "method": "calibrated"},
                "rationale": "Sponsor disengaged; an exec touch protects the renewal.",
            },
            org_id=DEMO_ORG,
        )
        await memory.record_outcome(
            ep_id, "approve", "Looks right, sending today.", {"nrr_projected": 108.0}
        )
        return ep_id

    asyncio.run(_seed_episode())

    body = client.get(f"/accounts/{account_id}/timeline").json()
    kinds = [e["kind"] for e in body["events"]]
    assert "recommendation" in kinds
    assert "decision" in kinds
    assert "outcome" in kinds
    assert body["counts"]["recommendation"] >= 1
    assert body["counts"]["decision"] >= 1
    assert body["counts"]["outcome"] >= 1

    # The recommendation event carries action + confidence.
    rec = next(e for e in body["events"] if e["kind"] == "recommendation")
    assert rec["action"]["title"] == "Schedule exec review"
    assert rec["confidence"]["score"] == 0.82

    # The decision event records the human verb and reason.
    dec = next(e for e in body["events"] if e["kind"] == "decision")
    assert dec["decision"] == "accepted"
    assert dec["reason"] == "Looks right, sending today."

    # Newest first: timestamps are non-increasing (None sorts last).
    stamps = [e["ts"] or "" for e in body["events"]]
    assert stamps == sorted(stamps, reverse=True)


def test_timeline_is_org_scoped(app, client) -> None:
    """One org never sees another org's account timeline or interactions."""

    other = _fresh_org_client(app)

    # A fresh org cannot read the demo org's seed account timeline.
    assert other.get("/accounts/ACC-1001/timeline").status_code == 404

    # The fresh org creates its own account and ingests an interaction for it.
    created = other.post("/accounts", json={"name": "Scoped Co"}).json()
    acc_id = created["account_id"]

    ing = other.post(
        "/ingest",
        json={
            "text": "Customer flagged a renewal blocker on pricing during the QBR.",
            "source_type": "meeting_notes",
            "title": "QBR notes",
            "account_id": acc_id,
            "domain": "customer_success",
        },
    )
    assert ing.status_code == 200, ing.text

    tl = other.get(f"/accounts/{acc_id}/timeline")
    assert tl.status_code == 200, tl.text
    body = tl.json()
    titles = [e["title"] for e in body["events"] if e["kind"] == "interaction"]
    assert "QBR notes" in titles
    # No demo seed documents leak into the fresh org's timeline.
    assert all(not str(e["id"]).startswith("doc:") for e in body["events"])

    # The demo org cannot see the fresh org's account at all.
    assert client.get(f"/accounts/{acc_id}/timeline").status_code == 404
