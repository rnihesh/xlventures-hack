"""Tenant-isolation tests for the action-execution API, all offline.

``POST /execute`` and ``GET /execute/{run_id}`` take a caller-supplied, opaque
``run_id``. They must act on (and read back) only artifacts for a run the
caller's org owns. These tests prove a cross-org caller cannot generate an
artifact from, or read the artifacts of, another tenant's run: both return 404
(not 403, to avoid an id-enumeration oracle; not the data), and the cross-org
write never lands in the store.
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
    # Consume the SSE stream to completion so a recommendation is recorded on the
    # run registry (the offline planner is deterministic and finite).
    assert client.get(f"/runs/{run_id}/stream").status_code == 200
    return run_id


def test_execute_happy_path_same_org(client) -> None:
    """The owner can generate an artifact for its run and read it back."""

    run_id = _make_run_with_recommendation(client)

    resp = client.post(
        "/execute", json={"run_id": run_id, "artifact_type": "email"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["artifact"]
    assert body["audit"]["run_id"] == run_id

    listed = client.get(f"/execute/{run_id}")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_execute_cross_org_is_404_and_not_written(client, app) -> None:
    """A foreign org cannot act on or read another tenant's run.

    The test client is logged in as the Demo org and owns the run. We swap the
    resolved org to an intruder: POST /execute must 404 with no artifact written,
    and GET /execute/{run_id} must 404 rather than leak (or empty-list) the
    owner's artifacts. The owner still sees exactly its own artifact afterwards.
    """

    run_id = _make_run_with_recommendation(client)

    # Owner generates one artifact so the run has stored, org-stamped records.
    assert (
        client.post(
            "/execute", json={"run_id": run_id, "artifact_type": "email"}
        ).status_code
        == 200
    )

    from app.api._org import current_org
    from app.api.execute import _ARTIFACTS

    before = len(_ARTIFACTS.get(run_id, []))

    app.dependency_overrides[current_org] = lambda: "org_intruder"
    try:
        blocked = client.post(
            "/execute", json={"run_id": run_id, "artifact_type": "email"}
        )
        assert blocked.status_code == 404
        # The cross-org write did not happen.
        assert len(_ARTIFACTS.get(run_id, [])) == before

        read = client.get(f"/execute/{run_id}")
        assert read.status_code == 404
    finally:
        app.dependency_overrides.pop(current_org, None)

    # The owner is unaffected: still exactly its own artifact, no intruder rows.
    after = client.get(f"/execute/{run_id}")
    assert after.status_code == 200
    assert len(after.json()) == before


def test_execute_unknown_run_id_with_inline_rec_still_works(client) -> None:
    """An inline recommendation under an unknown run_id is not blocked.

    A client-supplied run_id that names no stored run has no owner, so it is not
    treated as cross-org: the inline recommendation path still generates and
    files the artifact under that id for the caller's org.
    """

    rec = {
        "id": "rec-inline-1",
        "action": {"key": "send_check_in", "title": "Send a check-in"},
    }
    resp = client.post(
        "/execute",
        json={
            "run_id": "run-never-created",
            "recommendation": rec,
            "account_id": "ACC-1001",
            "artifact_type": "email",
        },
    )
    assert resp.status_code == 200
    assert client.get("/execute/run-never-created").status_code == 200
