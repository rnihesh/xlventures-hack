"""Ingest API (workflow step 1), fully offline.

Covers the live-evidence experience: a pasted interaction is stored, returns a
short title plus deterministically extracted signals, is idempotent on repeat,
shows up in the org's recent feed, and stays org-scoped.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.api._ingest_signals import RecentIngestStore, extract_signals

_TRANSCRIPT = (
    "QBR with the champion. Adoption of the analytics module stalled and two "
    "power users left. They are evaluating a competitor before the renewal in "
    "March. The customer is frustrated about pricing."
)


def _fresh_org_client(app) -> TestClient:
    """Sign up a brand-new org and return a logged-in client for it."""

    email = f"ingest_{uuid.uuid4().hex[:8]}@example.com"
    tc = TestClient(app)
    signup = tc.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "secret123",
            "name": "Ingest User",
            "org_name": f"Org {uuid.uuid4().hex[:6]}",
        },
    )
    assert signup.status_code == 201, signup.text
    login = tc.post("/auth/login", json={"email": email, "password": "secret123"})
    assert login.status_code == 200, login.text
    return tc


def test_extract_signals_is_deterministic_and_categorized() -> None:
    """Signal extraction surfaces categorized phrases with no LLM, repeatably."""

    first = extract_signals(_TRANSCRIPT)
    second = extract_signals(_TRANSCRIPT)
    assert first == second  # pure / deterministic
    assert first, "expected at least one extracted signal"
    categories = {s["category"] for s in first}
    assert {"renewal", "usage"} & categories
    assert all({"category", "label", "keyword", "text"} <= set(s) for s in first)

    assert extract_signals("") == []
    assert extract_signals("Let us meet for lunch tomorrow.") == []


def test_ingest_stores_and_returns_extracted_signals(client) -> None:
    """POST /ingest indexes the text and returns id, title, signals, chars."""

    res = client.post(
        "/ingest",
        json={
            "text": _TRANSCRIPT,
            "source_type": "call_transcript",
            "account_id": "ACC-signals",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["id"]
    assert body["chunks_written"] >= 1
    assert body["chars"] == len(_TRANSCRIPT.strip())
    assert body["source_type"] == "call_transcript"
    assert body["account_id"] == "ACC-signals"
    assert body["duplicate"] is False

    signals = body["extracted_signals"]
    assert signals, "ingest should return extracted signals"
    assert {s["category"] for s in signals} & {"renewal", "usage", "churn_risk"}


def test_ingest_is_idempotent_per_org(client) -> None:
    """Re-pasting identical content returns the original record, no duplicate."""

    payload = {
        "text": "Renewal call. Usage is healthy and they want to expand seats.",
        "source_type": "meeting_notes",
        "account_id": "ACC-idem",
    }
    first = client.post("/ingest", json=payload).json()
    second = client.post("/ingest", json=payload).json()

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["id"] == first["id"]


def test_ingest_recent_feed_and_account_filter(client) -> None:
    """The recent feed lists ingested interactions, newest first, by account."""

    tag = uuid.uuid4().hex[:6]
    acct = f"ACC-feed-{tag}"
    client.post(
        "/ingest",
        json={
            "text": f"Email thread {tag}. The customer may churn before renewal.",
            "source_type": "email",
            "account_id": acct,
        },
    )

    feed = client.get(f"/ingest/recent?account_id={acct}").json()["items"]
    assert len(feed) == 1
    assert feed[0]["account_id"] == acct
    assert feed[0]["extracted_signals"]

    miss = client.get("/ingest/recent?account_id=ACC-does-not-exist").json()["items"]
    assert miss == []


def test_recent_store_is_org_scoped() -> None:
    """An org only ever sees its own ingested evidence."""

    store = RecentIngestStore(cap=10)
    store.add("org_a", "fp1", {"id": "a1", "account_id": None, "title": "A"})
    store.add("org_b", "fp2", {"id": "b1", "account_id": None, "title": "B"})

    a_items = store.list("org_a")
    b_items = store.list("org_b")
    assert [i["id"] for i in a_items] == ["a1"]
    assert [i["id"] for i in b_items] == ["b1"]
    assert store.list("org_unknown") == []


def test_ingest_feed_is_org_isolated(app, client) -> None:
    """A second org does not see the first org's ingested interactions."""

    marker = uuid.uuid4().hex[:8]
    client.post(
        "/ingest",
        json={
            "text": f"Private note {marker}. Churn risk rising before renewal.",
            "source_type": "meeting_notes",
        },
    )

    other = _fresh_org_client(app)
    other_feed = other.get("/ingest/recent").json()["items"]
    assert all(marker not in (item.get("title") or "") for item in other_feed)
