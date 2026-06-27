"""Tests for the agent + tool catalog API.

Mounts the agents router on a standalone FastAPI app so the test exercises the
real router and registries without depending on how the main app wires it. All
assertions hold offline: the registries populate from the specialist module
imports (decorator side effects), no external services required.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agents import router as agents_router


@pytest.fixture()
def agents_client() -> TestClient:
    """A TestClient for a standalone app mounting just the agents router."""

    app = FastAPI()
    app.include_router(agents_router)
    return TestClient(app)


def test_get_agents_shape(agents_client: TestClient) -> None:
    """GET /agents returns capability cards with the expected fields."""

    resp = agents_client.get("/agents")
    assert resp.status_code == 200, resp.text
    body: List[Dict[str, Any]] = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1

    card = body[0]
    for key in ("name", "capability", "description", "output_keys", "cost_tier", "tags"):
        assert key in card, f"missing {key} in agent card"
    assert isinstance(card["output_keys"], list)
    assert isinstance(card["tags"], list)

    # The known specialists register their capabilities on import.
    capabilities = {c["capability"] for c in body}
    assert {"retrieval", "risk_scorer", "play_recommender", "critic"} <= capabilities


def test_get_tools_shape(agents_client: TestClient) -> None:
    """GET /tools returns governance-tagged tool specs."""

    resp = agents_client.get("/tools")
    assert resp.status_code == 200, resp.text
    body: List[Dict[str, Any]] = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1

    spec = body[0]
    for key in ("name", "description", "side_effecting", "risk_tier", "binding"):
        assert key in spec, f"missing {key} in tool spec"
    assert isinstance(spec["side_effecting"], bool)
