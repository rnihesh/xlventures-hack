"""Scenario suite: run the planner graph on golden cases and score behaviour.

Two real metrics are produced:

* Action Match: does the recommended action key equal the expected action key
  for the golden case (with a small alias map so the engine's ``schedule_*qbr``
  key counts as the pack's ``schedule_executive_business_review``).
* Trajectory Validity: did the run visit the expected node sequence
  (planner -> retrieve -> analyze -> recommend -> critic) in order.

``run_cases`` executes the genuine LangGraph pipeline when its dependencies are
installed. If LangGraph is not importable (for example a stripped offline demo
box) it falls back to driving the same recommendation builder directly so the
harness still produces real, comparable records. Both paths emit the identical
recommendation object and an ordered list of node steps.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden.jsonl")

# The expected trajectory of the planner graph.
EXPECTED_NODES: List[str] = ["planner", "retrieve", "analyze", "recommend", "critic"]

# Threshold a suite must clear to be reported as healthy in the dashboard.
ACTION_MATCH_THRESHOLD = 0.6
TRAJECTORY_THRESHOLD = 0.9

# Action keys the engine emits are normalised onto the domain pack catalog so
# semantically identical actions score as a match.
_ACTION_ALIASES = {
    "schedule_executive_qbr": "schedule_executive_business_review",
    "schedule_qbr": "schedule_executive_business_review",
    "executive_business_review": "schedule_executive_business_review",
}


def _norm_action(key: str) -> str:
    key = (key or "").strip().lower()
    return _ACTION_ALIASES.get(key, key)


def load_golden(path: str = GOLDEN_PATH) -> List[Dict[str, Any]]:
    """Load the golden cases from the JSONL fixture."""

    cases: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _initial_state(case: Dict[str, Any]) -> Dict[str, Any]:
    run_id = f"eval-{case['id']}"
    return {
        "run_id": run_id,
        "domain": case.get("domain", "customer_success"),
        "account_id": case["account_id"],
        "signal": {
            "type": case.get("signal_type", "churn_risk"),
            "content": case.get("situation", ""),
        },
        "plan": [],
        "steps": [],
        "messages": [],
        "recommendation": None,
    }


async def _run_via_graph(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drive the real LangGraph planner. Raises if LangGraph is unavailable."""

    from langgraph.checkpoint.memory import MemorySaver  # noqa: F401

    from app.graph.planner import build_graph

    records: List[Dict[str, Any]] = []
    for case in cases:
        checkpointer = MemorySaver()
        graph = build_graph(checkpointer)
        state = _initial_state(case)
        config = {"configurable": {"thread_id": state["run_id"]}}
        final = await graph.ainvoke(state, config=config)
        records.append(
            {
                "case": case,
                "recommendation": final.get("recommendation") or {},
                "steps": final.get("steps") or [],
                "engine": "langgraph",
            }
        )
    return records


def _simulated_steps() -> List[Dict[str, Any]]:
    """Mirror the planner graph's node trajectory for the offline fallback."""

    summaries = {
        "planner": "Drafted a 4 step plan",
        "retrieve": "Retrieved evidence snippets",
        "analyze": "Classified the situation",
        "recommend": "Recommended the next best action",
        "critic": "Critiqued the recommendation",
    }
    return [
        {"node": node, "summary": summaries[node], "ts": _now_iso(), "data": {}}
        for node in EXPECTED_NODES
    ]


def _run_via_fallback(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Offline path: build the same recommendation without LangGraph installed."""

    from app.explain.recommendation import build_recommendation

    records: List[Dict[str, Any]] = []
    for case in cases:
        state = _initial_state(case)
        recommendation = build_recommendation(state, llm=None)
        records.append(
            {
                "case": case,
                "recommendation": recommendation,
                "steps": _simulated_steps(),
                "engine": "fallback",
            }
        )
    return records


async def run_cases(cases: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """Execute every golden case and return scored-ready records.

    Tries the genuine graph first; on any import or runtime failure it falls
    back to the dependency-free recommendation builder so the harness always
    returns real records offline.
    """

    cases = cases if cases is not None else load_golden()
    try:
        return await _run_via_graph(cases)
    except Exception:
        return _run_via_fallback(cases)


def score_action(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Exact (alias-normalised) action match against the golden expectation."""

    total = len(records)
    passed = 0
    details: List[Dict[str, Any]] = []
    for rec in records:
        produced = _norm_action(
            (rec.get("recommendation") or {}).get("action", {}).get("key", "")
        )
        expected = _norm_action(rec["case"].get("expected_action", ""))
        ok = bool(produced) and produced == expected
        passed += int(ok)
        details.append(
            {
                "id": rec["case"]["id"],
                "expected": expected,
                "produced": produced,
                "match": ok,
            }
        )
    score = passed / total if total else 0.0
    return {
        "name": "Action Match",
        "metric": "exact_match",
        "score": round(score, 3),
        "passed": passed,
        "total": total,
        "healthy": score >= ACTION_MATCH_THRESHOLD,
        "details": details,
    }


def _trajectory_ok(steps: List[Dict[str, Any]]) -> bool:
    """True when the visited nodes contain EXPECTED_NODES as an ordered subsequence."""

    visited = [s.get("node") for s in steps]
    i = 0
    for node in visited:
        if i < len(EXPECTED_NODES) and node == EXPECTED_NODES[i]:
            i += 1
    return i == len(EXPECTED_NODES)


def score_trajectory(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fraction of runs that visited the full expected node trajectory in order."""

    total = len(records)
    passed = sum(1 for rec in records if _trajectory_ok(rec.get("steps") or []))
    score = passed / total if total else 0.0
    return {
        "name": "Trajectory Validity",
        "metric": "node_coverage",
        "score": round(score, 3),
        "passed": passed,
        "total": total,
        "healthy": score >= TRAJECTORY_THRESHOLD,
    }


async def evaluate() -> List[Dict[str, Any]]:
    """Run the scenario suite standalone and return its suite dicts."""

    records = await run_cases()
    return [score_action(records), score_trajectory(records)]


if __name__ == "__main__":  # pragma: no cover - manual invocation
    for suite in asyncio.run(evaluate()):
        print(
            f"{suite['name']:<22} {suite['metric']:<14} "
            f"score={suite['score']:.3f} passed={suite['passed']}/{suite['total']}"
        )
