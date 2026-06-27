"""Offline tests for the read-only decision brief endpoint.

GET /runs/{id}/brief projects a stored run, its recommendation, policy gate,
human decision, and episode outcome into a single self-contained artifact. It
never re-runs the graph or calls an LLM, so these assertions hold without
OPENAI_API_KEY or DATABASE_URL. The org-scoping case proves a run is never
leaked across tenants.
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
    # Consume the SSE stream to completion; the offline planner is deterministic
    # and finite, so this records the recommendation onto the run registry.
    resp = client.get(f"/runs/{run_id}/stream")
    assert resp.status_code == 200
    return run_id


def test_brief_shape(client) -> None:
    """The brief is a complete, self-contained one-pager for a finished run."""

    run_id = _make_run_with_recommendation(client)

    resp = client.get(f"/runs/{run_id}/brief")
    assert resp.status_code == 200
    brief = resp.json()

    # Top-level shape: every section the CSM hands to leadership is present.
    for field in (
        "run_id",
        "generated_at",
        "account",
        "signal",
        "recommendation",
        "confidence",
        "expected_impact",
        "evidence",
        "signals",
        "alternatives",
        "policy",
        "missing_information",
        "human_decision",
        "outcome",
    ):
        assert field in brief, f"brief missing {field}"

    assert brief["run_id"] == run_id

    # Account + signal context.
    assert brief["account"]["account_id"] == "ACC-1001"
    assert brief["signal"]["content"]

    # The next best action and its reasoning.
    rec = brief["recommendation"]
    assert rec["action"].get("title")
    assert "reasoning" in rec

    # Confidence carries score + label + method.
    for key in ("score", "label", "method"):
        assert key in brief["confidence"]

    # Evidence, alternatives, and policy are list/dict containers (possibly empty).
    assert isinstance(brief["evidence"], list)
    assert isinstance(brief["alternatives"], list)
    assert brief["policy"] is None or "summary" in brief["policy"]


def test_brief_org_scoping(client, app) -> None:
    """A run's brief is never readable by another org (404, no leak)."""

    run_id = _make_run_with_recommendation(client)
    assert client.get(f"/runs/{run_id}/brief").status_code == 200

    # Swap the resolved org to a foreign tenant; the run must vanish.
    from app.api._org import current_org

    app.dependency_overrides[current_org] = lambda: "org_intruder"
    try:
        resp = client.get(f"/runs/{run_id}/brief")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(current_org, None)


def test_brief_missing_recommendation_conflicts(client) -> None:
    """A run with no recommendation yet returns 409, not a half-built brief."""

    payload = {
        "domain": "customer_success",
        "account_id": "ACC-1001",
        "signal": {"type": "usage_drop", "content": "Usage softening"},
    }
    run_id = client.post("/runs", json=payload).json()["run_id"]
    # No stream consumed, so no recommendation has been recorded.
    resp = client.get(f"/runs/{run_id}/brief")
    assert resp.status_code == 409
