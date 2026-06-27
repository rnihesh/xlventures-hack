"""Tests for configurable rules: the overrides store, the merge, and the API.

All assertions hold offline (no DATABASE_URL): the pack_overrides repository
round-trips through its in-memory fallback, the loader merges an org override
onto the base pack (add / edit / remove), and the /rules API returns the
effective merged view.

The API test mounts the rules router on a standalone FastAPI app with the
current-org dependency overridden, so it exercises the real router, repository,
and merge without depending on how the main app wires the router.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api._org import current_org
from app.api.rules import router as rules_router
from app.packs.loader import effective_rules
from app.repositories import pack_overrides as overrides_repo

DOMAIN = "customer_success"


async def test_overrides_upsert_get_delete() -> None:
    """The repository round-trips an override through the offline store."""

    org = "org_test_rules"
    await overrides_repo.delete(org, DOMAIN)
    assert await overrides_repo.get_overrides(org, DOMAIN) == {}

    payload = {"actions": [{"key": "new_play", "title": "A new play"}]}
    saved = await overrides_repo.upsert(org, DOMAIN, payload)
    assert saved["org_id"] == org
    assert saved["domain"] == DOMAIN
    assert saved["overrides"]["actions"][0]["key"] == "new_play"

    again = await overrides_repo.get_overrides(org, DOMAIN)
    assert again["actions"][0]["title"] == "A new play"

    # Scoping: another org sees nothing of this org's override.
    assert await overrides_repo.get_overrides("org_other", DOMAIN) == {}

    assert await overrides_repo.delete(org, DOMAIN) is True
    assert await overrides_repo.get_overrides(org, DOMAIN) == {}


def test_effective_rules_no_override_returns_base() -> None:
    """With no override the effective view equals the base pack."""

    merged = effective_rules(DOMAIN, {})
    assert len(merged["policies"]) >= 1
    assert len(merged["actions"]) >= 1
    ids = {p["id"] for p in merged["policies"]}
    assert "discount_cap_15" in ids


def test_effective_rules_edit_add_remove() -> None:
    """An override can edit a base rule, add a new one, and drop the rest."""

    base = effective_rules(DOMAIN, {})
    base_ids = [p["id"] for p in base["policies"]]
    assert "discount_cap_15" in base_ids

    override = {
        "policies": [
            # Edit: keep an existing rule but tighten its cap (partial entry,
            # the base type/condition fields are backfilled by the merge).
            {"id": "discount_cap_15", "condition": {"max_pct": 10}},
            # Add: a brand new rule not present in the base pack.
            {
                "id": "custom_floor",
                "description": "Custom confidence floor.",
                "type": "confidence_floor",
                "condition": {"min": 0.8},
                "severity": "high",
                "requires_approval": True,
            },
        ]
    }
    merged = effective_rules(DOMAIN, override)
    out_ids = [p["id"] for p in merged["policies"]]

    # Membership is defined by the override list (removal of unlisted rules).
    assert out_ids == ["discount_cap_15", "custom_floor"]

    edited = next(p for p in merged["policies"] if p["id"] == "discount_cap_15")
    assert edited["condition"]["max_pct"] == 10
    # Backfill: the omitted base fields survive the partial edit.
    assert edited["type"] == "discount_cap"
    assert edited["description"]  # inherited from the base rule


@pytest.fixture()
def rules_client() -> TestClient:
    """A TestClient for a standalone app mounting just the rules router."""

    app = FastAPI()
    app.include_router(rules_router)
    app.dependency_overrides[current_org] = lambda: "org_api_rules"
    return TestClient(app)


def test_get_rules_returns_effective_view(rules_client: TestClient) -> None:
    """GET /rules/{domain} returns merged policies + actions for the org."""

    resp = rules_client.get(f"/rules/{DOMAIN}")
    assert resp.status_code == 200, resp.text
    body: Dict[str, Any] = resp.json()
    assert body["domain"] == DOMAIN
    assert body["has_override"] is False
    assert any(p["id"] == "discount_cap_15" for p in body["policies"])
    assert any(a["key"] for a in body["actions"])


def test_put_then_get_rules_persists_override(rules_client: TestClient) -> None:
    """PUT saves the org override and GET reflects the merged result."""

    payload = {
        "policies": [
            {"id": "discount_cap_15", "condition": {"max_pct": 5}},
        ],
        "actions": [
            {"key": "custom_play", "title": "Custom play", "description": "Org-specific play."},
        ],
    }
    put = rules_client.put(f"/rules/{DOMAIN}", json=payload)
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["has_override"] is True
    assert [p["id"] for p in saved["policies"]] == ["discount_cap_15"]
    assert saved["policies"][0]["condition"]["max_pct"] == 5
    assert [a["key"] for a in saved["actions"]] == ["custom_play"]

    got = rules_client.get(f"/rules/{DOMAIN}").json()
    assert got["has_override"] is True
    assert got["actions"][0]["key"] == "custom_play"

    # Clearing the override reverts to the base pack.
    cleared = rules_client.put(f"/rules/{DOMAIN}", json={})
    assert cleared.status_code == 200
    assert cleared.json()["has_override"] is False
