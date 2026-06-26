"""Aggregate every eval suite into the /eval response shape.

``run_all`` runs the golden cases through the planner once, scores all three
suites against the shared records, writes a cached snapshot, and returns the
exact payload the ``/eval`` endpoint serves:

    {
      "suites":   [{name, metric, score, passed, total}, ...],
      "outcomes": {kpi, baseline, projected, unit}
    }

Callable from the CLI: ``python -m app.eval.runner``.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.api._org import DEMO_ORG
from app.eval import component, outcome, scenario

CACHE_PATH = os.path.join(os.path.dirname(__file__), "_last_run.json")

# Keys the /eval contract requires on every suite entry.
_SUITE_KEYS = ("name", "metric", "score", "passed", "total")


def _slim_suite(suite: Dict[str, Any]) -> Dict[str, Any]:
    """Project a suite dict down to the contract fields (plus a healthy flag)."""

    out = {key: suite[key] for key in _SUITE_KEYS}
    out["healthy"] = bool(suite.get("healthy", suite["score"] >= 0.6))
    return out


async def run_all(org_id: str = DEMO_ORG) -> Dict[str, Any]:
    """Run all suites against one shared set of golden-case records.

    The golden-case SUITES (grounding, faithfulness, action match, trajectory)
    are platform engine-quality metrics and stay global. The OUTCOMES block is
    org-scoped: ``org_id`` threads through to ``compute_outcomes`` so a new empty
    org sees honest empty numbers, never another org's (or the seed) figures.
    """

    cases = scenario.load_golden()
    records = await scenario.run_cases(cases)

    suites: List[Dict[str, Any]] = [
        component.score_grounding(records),
        component.score_faithfulness(records),
        scenario.score_action(records),
        scenario.score_trajectory(records),
    ]

    outcome_suite, headline, breakdown = await outcome.compute_outcomes(records, org_id)
    suites.append(outcome_suite)

    payload = {
        "suites": [_slim_suite(s) for s in suites],
        "outcomes": headline,
        "breakdown": breakdown,
        "engine": records[0]["engine"] if records else "none",
        "case_count": len(records),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_cache(payload)
    return payload


async def eval_for_org(org_id: str = DEMO_ORG) -> Dict[str, Any]:
    """Fast path for GET /eval: serve the cached engine suites and compute only
    the org-scoped OUTCOMES (cheap, no LLM). Never re-runs the golden cases on a
    dashboard request, so the endpoint cannot hang. Run ``python -m
    app.eval.runner`` (or refresh) to refresh the engine suites.
    """

    cache = load_cached() or {}
    cached_suites = cache.get("suites", []) or []
    # Drop the cached (stale, possibly other-org) outcome suite; recompute ours.
    engine_suites = [s for s in cached_suites if s.get("metric") != "kpis_improved"]

    outcome_suite, headline, breakdown = await outcome.compute_outcomes([], org_id)
    suites = engine_suites + [_slim_suite(outcome_suite)]

    return {
        "suites": suites,
        "outcomes": headline,
        "breakdown": breakdown,
        "engine": cache.get("engine", "cached"),
        "case_count": cache.get("case_count", 0),
        "generated_at": cache.get("generated_at"),
    }


def _write_cache(payload: Dict[str, Any]) -> None:
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except OSError:
        pass


def load_cached() -> Dict[str, Any] | None:
    """Return the last cached run, or None if none exists or it is unreadable."""

    if not os.path.exists(CACHE_PATH):
        return None
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _print_summary(payload: Dict[str, Any]) -> None:
    print("=" * 64)
    print(f"Eval run ({payload['engine']} engine, {payload['case_count']} golden cases)")
    print("=" * 64)
    for suite in payload["suites"]:
        flag = "PASS" if suite["healthy"] else "WARN"
        print(
            f"[{flag}] {suite['name']:<24} {suite['metric']:<14} "
            f"score={suite['score']:.3f}  passed={suite['passed']}/{suite['total']}"
        )
    out = payload["outcomes"]
    print("-" * 64)
    print(
        f"Headline KPI: {out['kpi']} "
        f"{out['baseline']} -> {out['projected']} {out['unit']}"
    )
    acc = payload["breakdown"]["acceptance"]
    print(
        f"Acceptance:   {acc['rate']:.0%} "
        f"({acc['accepted']}/{acc['decided']}, source={acc['source']}) "
        f"vs baseline {acc['baseline_rate']:.0%}"
    )
    print(f"Cached to:    {CACHE_PATH}")


def main() -> None:
    payload = asyncio.run(run_all())
    _print_summary(payload)


if __name__ == "__main__":
    main()
