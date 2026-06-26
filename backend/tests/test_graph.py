"""Planner graph integration test.

Builds the real LangGraph planner with an in-memory checkpointer and runs the
full pipeline (planner -> retrieval -> risk_scorer -> play_recommender ->
outcome_simulator -> drafter -> critic -> policy_gate -> hitl_gate -> commit)
on a seeded account. Asserts the run yields an Explainable Recommendation
Object carrying the load-bearing fields the UI and contract depend on.
"""

from __future__ import annotations

from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver

from app.graph.planner import build_graph


def _seed_state() -> Dict[str, Any]:
    """Initial run state for a high-risk seeded customer-success account."""

    return {
        "run_id": "test-run-graph",
        "domain": "customer_success",
        "account_id": "ACC-1001",
        "signal": {
            "type": "usage_drop",
            "content": "Usage down 38% QoQ; sponsor disengaged ahead of renewal",
        },
        "plan": [],
        "capabilities": [],
        "steps": [],
        "messages": [],
        "recommendation": None,
    }


async def test_graph_produces_recommendation() -> None:
    """The compiled graph runs end to end and emits a complete recommendation."""

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test-run-graph"}}

    final = await graph.ainvoke(_seed_state(), config=config)

    rec = final.get("recommendation")
    assert isinstance(rec, dict), "the planner must produce a recommendation"

    # Required, load-bearing fields.
    action = rec["action"]
    assert action["key"] and action["title"]

    evidence = rec["evidence"]
    assert isinstance(evidence, list) and evidence
    for item in evidence:
        for field in ("claim", "source_id", "source_type", "snippet", "span"):
            assert field in item

    confidence = rec["confidence"]
    assert 0.0 <= float(confidence["score"]) <= 1.0
    assert confidence["label"] in {"low", "medium", "high"}

    # The policy gate must have attached its declarative guardrail results.
    policy = rec["policy"]
    assert isinstance(policy, list) and policy
    for gate in policy:
        assert gate["status"] in {"pass", "fail", "warn"}

    # The commit node wrote a learnable episode to memory.
    assert final.get("episode_id")

    # The trace records each node that ran, including the critic and policy gate.
    nodes_run = {step["node"] for step in final.get("steps", [])}
    assert {"planner", "critic", "policy_gate", "commit"}.issubset(nodes_run)
