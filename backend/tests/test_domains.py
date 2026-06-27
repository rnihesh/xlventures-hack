"""Tests for the extensibility flow: validate and store org-uploaded domain packs.

All assertions hold offline (no DATABASE_URL): the org_packs repository
round-trips through its in-memory fallback, pack validation rejects a bad pack
and accepts a good one, and the /domains API merges an org's uploaded pack into
the domain list, scoped so one org never sees another org's uploads.

The API tests mount the domains router on a standalone FastAPI app with the
current-org dependency overridden, so they exercise the real router, repository,
loader, and schema without depending on how the main app wires the router.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api._org import current_org
from app.api.domains import router as domains_router
from app.packs.loader import load_pack, reset_pack_org, set_pack_org
from app.packs.schema import PackValidationError, validate_pack
from app.repositories import org_packs as org_packs_repo

# A minimal but complete pack for a brand new domain.
GOOD_YAML = """
domain: field_service
display_name: "Field Service Dispatch"
signals:
  - key: sla_breach_risk
    label: "Work order at risk of breaching its SLA"
    source_type: ticket
decision_points:
  sla_at_risk:
    label: "SLA at risk"
    description: "An open work order may miss its committed SLA."
    trigger_signals: [sla_breach_risk]
    primary_kpi: sla_attainment
    default_persona: dispatcher
actions:
  - key: expedite_dispatch
    title: "Expedite dispatch"
    description: "Assign the nearest qualified technician now."
    eligible_points: [sla_at_risk]
kpis:
  - key: sla_attainment
    label: "SLA Attainment"
    unit: percent
    target: ">= 95"
"""

# Missing the required ``domain`` key and a wrong-typed actions section.
BAD_YAML = """
display_name: "Broken Pack"
actions: "this should be a list, not a string"
"""


def test_validate_rejects_bad_pack() -> None:
    """A pack missing its domain key (and malformed) is rejected with messages."""

    import yaml

    with pytest.raises(PackValidationError) as exc:
        validate_pack(yaml.safe_load(BAD_YAML))
    assert exc.value.errors  # at least one human readable message.
    assert any("domain" in msg for msg in exc.value.errors)


def test_validate_accepts_good_pack() -> None:
    """A complete pack validates into a DomainPack with the expected shape."""

    import yaml

    pack = validate_pack(yaml.safe_load(GOOD_YAML))
    assert pack.domain == "field_service"
    assert len(pack.actions) == 1
    assert "sla_at_risk" in pack.decision_points


async def test_repo_upsert_is_org_scoped_and_resolves_in_loader() -> None:
    """A saved org pack round-trips, is org scoped, and loads for a run."""

    org = "org_test_domains"
    other = "org_other_domains"
    domain = "field_service"
    await org_packs_repo.delete(org, domain)

    saved = await org_packs_repo.upsert(org, GOOD_YAML)
    assert saved["org_id"] == org
    assert saved["domain"] == domain
    assert saved["parsed"]["display_name"] == "Field Service Dispatch"

    # Scoping: the owning org sees the pack, another org does not.
    mine = {r["domain"] for r in await org_packs_repo.list_for_org(org)}
    theirs = {r["domain"] for r in await org_packs_repo.list_for_org(other)}
    assert domain in mine
    assert domain not in theirs

    # A run on the new domain resolves the uploaded pack through the loader.
    token = set_pack_org(org)
    try:
        pack = load_pack(domain)
        assert pack.domain == domain
        assert any(a.key == "expedite_dispatch" for a in pack.actions)
    finally:
        reset_pack_org(token)

    assert await org_packs_repo.delete(org, domain) is True


@pytest.fixture()
def domains_client() -> TestClient:
    """A TestClient for a standalone app mounting just the domains router."""

    app = FastAPI()
    app.include_router(domains_router)
    app.dependency_overrides[current_org] = lambda: "org_api_domains"
    return TestClient(app)


def test_validate_endpoint_reports_errors_and_summary(domains_client: TestClient) -> None:
    """POST /domains/validate returns ok=false with errors, ok=true with a summary."""

    bad = domains_client.post("/domains/validate", json={"yaml": BAD_YAML})
    assert bad.status_code == 200, bad.text
    assert bad.json()["ok"] is False
    assert bad.json()["errors"]

    good = domains_client.post("/domains/validate", json={"yaml": GOOD_YAML})
    assert good.status_code == 200, good.text
    body = good.json()
    assert body["ok"] is True
    assert body["summary"]["decision_points"] == 1
    assert body["summary"]["actions"] == 1


def test_saved_pack_appears_in_domains_for_that_org_only(
    domains_client: TestClient,
) -> None:
    """A saved org pack appears in GET /domains for its org but not another org."""

    # Clean slate, then save the new domain.
    domains_client.delete("/domains/field_service")
    save = domains_client.post("/domains", json={"yaml": GOOD_YAML})
    assert save.status_code == 201, save.text
    assert save.json()["domain"] == "field_service"

    listed = domains_client.get("/domains")
    assert listed.status_code == 200, listed.text
    items = {d["key"]: d for d in listed.json()}
    assert "field_service" in items
    assert items["field_service"]["source"] == "org"
    assert items["field_service"]["editable"] is True

    # The full pack is fetchable for this org.
    full = domains_client.get("/domains/field_service")
    assert full.status_code == 200, full.text
    assert full.json()["domain"] == "field_service"

    # A different org does not see this org's uploaded pack.
    other_app = FastAPI()
    other_app.include_router(domains_router)
    other_app.dependency_overrides[current_org] = lambda: "org_unrelated_domains"
    other_client = TestClient(other_app)
    other = other_client.get("/domains")
    assert "field_service" not in {d["key"] for d in other.json()}

    # Delete reverts the list.
    deleted = domains_client.delete("/domains/field_service")
    assert deleted.status_code == 200, deleted.text
    after = {d["key"] for d in domains_client.get("/domains").json()}
    assert "field_service" not in after


def test_save_rejects_invalid_pack(domains_client: TestClient) -> None:
    """POST /domains refuses an invalid pack with a 422 and error messages."""

    resp = domains_client.post("/domains", json={"yaml": BAD_YAML})
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["errors"]


# ---------------------------------------------------------------------------
# Domain-understanding surface: the enriched narrative fields must parse for
# every shipped pack, and they must stay additive (a lean pack without them
# still validates). All assertions are offline: load straight from disk.
# ---------------------------------------------------------------------------

BASE_PACKS = ["customer_success", "saas_sales", "collections"]


@pytest.mark.parametrize("domain", BASE_PACKS)
def test_enriched_base_pack_parses_with_narrative_fields(domain: str) -> None:
    """Each base pack parses and carries the new narrative fields."""

    pack = load_pack(domain)
    assert pack.domain == domain
    # The new fields are present and the right shape.
    assert pack.tagline, f"{domain} should declare a tagline"
    assert pack.business_process, f"{domain} should declare business_process stages"
    assert pack.customer_journey, f"{domain} should declare a customer_journey"
    assert pack.success_metrics, f"{domain} should declare success_metrics"

    # Every decision point has a description and a plain-language "when".
    assert pack.decision_points
    for key, dp in pack.decision_points.items():
        assert dp.description, f"{domain}.{key} missing a description"
        assert dp.when, f"{domain}.{key} missing a 'when' trigger description"

    # Each success metric is legible: it names what it measures.
    for metric in pack.success_metrics:
        assert metric.name and metric.definition


def test_customer_success_is_the_richest_pack() -> None:
    """The flagship pack carries the full onboarding -> expansion journey."""

    pack = load_pack("customer_success")
    journey_keys = [s.key for s in pack.customer_journey]
    for expected in ("onboarding", "adoption", "renewal", "expansion"):
        assert expected in journey_keys
    # The headline retention metrics are modeled as success metrics.
    metric_keys = {m.key for m in pack.success_metrics}
    assert {"NRR", "GRR", "churn_rate", "health_score", "time_to_value"} <= metric_keys


def test_narrative_fields_are_additive_and_dumped() -> None:
    """A pack without narrative fields still validates, and a rich pack dumps them.

    Backward compatibility: GOOD_YAML declares none of the new fields and still
    parses with safe empty defaults. Forward compatibility: the full pack
    model_dump carries the narrative fields so the /domains/{key} API can expose
    them to the overview UI.
    """

    import yaml

    lean = validate_pack(yaml.safe_load(GOOD_YAML))
    assert lean.tagline == ""
    assert lean.business_process == []
    assert lean.customer_journey == []
    assert lean.success_metrics == []
    # Decision points without an explicit "when" default to an empty string.
    assert lean.decision_points["sla_at_risk"].when == ""

    dumped = load_pack("customer_success").model_dump()
    for field in ("tagline", "business_process", "customer_journey", "success_metrics"):
        assert field in dumped
    assert "when" in dumped["decision_points"]["renewal_risk"]
