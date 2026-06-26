"""End-to-end API tests against app.main:app, all offline.

These exercise the real routers (no mocks): the deterministic seeds, the
domain-pack loader, the policy engine, the eval runner, and the offline
artifact generators. Every assertion holds without OPENAI_API_KEY or
DATABASE_URL.
"""

from __future__ import annotations

from typing import Any, Dict, List


def test_health(client) -> None:
    """Liveness probe returns the ok status envelope."""

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_accounts_inbox(client) -> None:
    """The triage inbox lists seeded accounts, highest risk first."""

    resp = client.get("/accounts")
    assert resp.status_code == 200
    accounts: List[Dict[str, Any]] = resp.json()
    assert isinstance(accounts, list) and len(accounts) >= 3

    # Every summary carries the contract fields the inbox renders.
    for account in accounts:
        for field in ("account_id", "name", "domain", "health_score", "risk_level"):
            assert field in account

    # Sorted with highest risk ahead of lowest (risk ordering is part of the API).
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ranks = [order.get(a["risk_level"], 4) for a in accounts]
    assert ranks == sorted(ranks)

    # A known seeded account is reachable on the 360 endpoint.
    detail = client.get("/accounts/ACC-1001")
    assert detail.status_code == 200
    body = detail.json()
    assert body["profile"]["account_id"] == "ACC-1001"
    assert isinstance(body["signals"], list) and body["signals"]


def test_domains_lists_all_three_packs(client) -> None:
    """/domains surfaces all three packs, including collections."""

    resp = client.get("/domains")
    assert resp.status_code == 200
    packs = resp.json()
    keys = {p["key"] for p in packs}

    # The reusability story: three verticals on disk, collections among them.
    assert {"customer_success", "saas_sales", "collections"}.issubset(keys)

    for pack in packs:
        assert pack["actions_count"] >= 0
        assert pack["decision_points_count"] >= 0

    # The full pack for collections parses and round-trips through the API.
    one = client.get("/domains/collections")
    assert one.status_code == 200
    detail = one.json()
    assert detail["domain"] == "collections"
    assert detail["decision_points"]


def test_learning_surface(client) -> None:
    """/learning returns episodes, an acceptance rate, and a before/after KPI."""

    resp = client.get("/learning")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["episodes"], list)
    assert 0.0 <= body["accepted_rate"] <= 1.0

    before_after = body["before_after"]
    for field in ("kpi", "before", "after", "note"):
        assert field in before_after


def test_gen_runs_populates_real_learning_metrics(client) -> None:
    """gen_runs drives real graph runs so /learning reflects real outcomes.

    Asserts the acceptance trend, counts, and projected before/after are all
    computed from the episodes the planner genuinely produced (not fixtures).
    """

    import asyncio

    from app.gen_runs import generate

    summary = asyncio.run(generate(6, force=True))
    assert summary["skipped"] is False
    assert summary["decided"] == summary["runs"] >= 1

    body = client.get("/learning").json()
    assert body["has_data"] is True
    assert body["decided"] >= summary["decided"]
    # Acceptance rate is approved-or-edited over decided, in [0, 1].
    assert 0.0 <= body["accepted_rate"] <= 1.0
    # The trend is a real cumulative-acceptance series, one point per decision.
    trend = body["trend"]
    assert isinstance(trend, list) and len(trend) == body["decided"]
    assert all(0.0 <= p["rate"] <= 1.0 for p in trend)
    assert [p["index"] for p in trend] == list(range(1, len(trend) + 1))
    # Projected before/after is labeled a projection and carries real data.
    assert body["before_after"]["projected"] is True
    assert body["before_after"]["has_data"] is True


def test_eval_suites_and_outcomes(client) -> None:
    """/eval returns scored suites and a headline business outcome."""

    resp = client.get("/eval")
    assert resp.status_code == 200
    body = resp.json()

    suites = body["suites"]
    assert isinstance(suites, list) and suites
    for suite in suites:
        for field in ("name", "metric", "score", "passed", "total"):
            assert field in suite
        assert 0.0 <= suite["score"] <= 1.0

    outcomes = body["outcomes"]
    for field in ("kpi", "baseline", "projected", "unit"):
        assert field in outcomes


def test_create_run_returns_run_id(client) -> None:
    """POST /runs creates a run and returns its identifier."""

    payload = {
        "domain": "customer_success",
        "account_id": "ACC-1001",
        "signal": {"type": "usage_drop", "content": "Usage down 38% QoQ; sponsor disengaged"},
    }
    resp = client.post("/runs", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body and body["run_id"]


def test_policy_evaluate(client) -> None:
    """POST /policy/evaluate scores a recommendation against domain rules.

    An over-cap concession trips the discount gate and forces approval.
    """

    recommendation = {
        "action": {
            "key": "offer_save_concession",
            "title": "Offer a 25% save concession",
            "description": "Offer a 25% retention discount to secure the renewal.",
        },
        "discount_pct": 25,
        "confidence": {"score": 0.8},
    }
    resp = client.post(
        "/policy/evaluate",
        json={
            "recommendation": recommendation,
            "account_id": "ACC-1001",
            "domain": "customer_success",
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    results = body["results"]
    assert isinstance(results, list) and results
    for gate in results:
        assert gate["status"] in {"pass", "fail", "warn"}

    # The 25% discount exceeds the 15% cap, so that gate fails and approval is forced.
    statuses = {g["rule_id"]: g["status"] for g in results}
    assert any(s == "fail" for s in statuses.values())
    assert body["requires_approval"] is True
    assert body["summary"]["total"] == len(results)


def test_execute_email_artifact(client) -> None:
    """POST /execute turns a recommendation into an offline email artifact."""

    recommendation = {
        "id": "rec-test-1",
        "account_id": "ACC-1001",
        "action": {
            "key": "schedule_executive_business_review",
            "title": "Schedule an executive business review",
            "description": "Book a strategic review with the buying committee before renewal.",
        },
        "rationale": "Usage is declining sharply ahead of renewal.",
        "confidence": {"score": 0.82, "label": "high"},
        "expected_impact": {"kpi": "NRR", "direction": "up", "estimate": "+4 to +6 points"},
    }
    resp = client.post(
        "/execute",
        json={
            "recommendation": recommendation,
            "account_id": "ACC-1001",
            "artifact_type": "email",
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    artifact = body["artifact"]
    assert artifact.get("subject")
    assert artifact.get("body")

    audit = body["audit"]
    assert audit["artifact_type"] == "email"
    # Offline: the deterministic template path, never the LLM.
    assert audit["source"] == "template"
