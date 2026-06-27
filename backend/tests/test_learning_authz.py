"""Authorization tests for the learning-outcome write path, all offline.

``POST /learning/outcome`` takes an opaque, caller-supplied ``episode_id``. It
must record an outcome only against an episode the caller's org owns. These
tests prove a caller cannot write an outcome onto another org's episode and that
the endpoint reveals nothing that would let it enumerate other tenants' ids.
"""

from __future__ import annotations

import asyncio

from app.memory.store import get_memory


def _write_episode_for_org(org_id: str) -> str:
    """Seed one pending episode owned by ``org_id`` and return its id."""

    memory = get_memory()
    return asyncio.run(
        memory.write_episode(
            account_id="ACC-OTHER",
            domain="customer_success",
            situation="Other tenant's private churn signal.",
            action_key="schedule_executive_business_review",
            recommendation={"action": {"key": "schedule_executive_business_review"}},
            org_id=org_id,
        )
    )


def test_outcome_on_other_orgs_episode_is_404_and_not_recorded(client) -> None:
    """A cross-org episode_id returns 404 and leaves the episode untouched.

    The test client is logged in as the Demo org. We plant an episode owned by a
    different org, then post an outcome for it: the write must be rejected with
    404 (not 403, to avoid an id-enumeration oracle) and the episode's outcome
    must stay ``pending``, so no learning signal leaks across the tenant boundary.
    """

    episode_id = _write_episode_for_org("org_intruder_target")

    resp = client.post(
        "/learning/outcome",
        json={"episode_id": episode_id, "decision": "approve", "reason": "nope"},
    )

    assert resp.status_code == 404

    # The episode the caller does not own was not mutated.
    memory = get_memory()
    episode = memory.get_episode(episode_id)
    assert episode is not None
    assert episode.outcome is not None
    assert episode.outcome.decision == "pending"


def test_outcome_for_unknown_episode_is_404(client) -> None:
    """A made-up episode_id is indistinguishable from a non-owned one: 404."""

    resp = client.post(
        "/learning/outcome",
        json={"episode_id": "ep-does-not-exist", "decision": "approve"},
    )
    assert resp.status_code == 404


def test_outcome_on_own_episode_is_recorded(client) -> None:
    """The happy path still works: the Demo org can write its own outcome.

    Episodes with no ``org_id`` belong to the Demo org (seeded history), so the
    Demo caller can record against one and the aggregate response stays scoped.
    """

    episode_id = _write_episode_for_org("org_demo")

    resp = client.post(
        "/learning/outcome",
        json={"episode_id": episode_id, "decision": "approve"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "recorded"
    assert 0.0 <= body["accepted_rate"] <= 1.0

    memory = get_memory()
    episode = memory.get_episode(episode_id)
    assert episode is not None and episode.outcome is not None
    assert episode.outcome.decision == "accepted"
