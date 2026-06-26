"""Outcome suite: projected business impact, baseline versus platform.

This module computes the headline business outcomes for ``/eval``. They are a
clearly-labeled PROJECTION, not actuals: baseline (a manual-triage reference)
versus a platform projection derived from the outcome simulator's per-action
estimates across the requesting org's own accounts, weighted by how confident the
engine is and how often that org's humans actually accept its recommendations. A
new org with no accounts and no decisions gets an honest empty headline, not the
seed corpus numbers.

Honesty rules baked in here:

* Acceptance is read from REAL recorded decisions in the memory/learning store
  when any exist (``source: "memory"``). With no decisions yet, the projection
  falls back to the engine's own average confidence as the expected-adoption
  factor (``source: "projection"``); it never invents a fake decision log.
* Every KPI is marked ``projected: true`` and carries a ``method`` note. The
  dollar figure (``arr_at_risk_addressed``) is computed from the real ARR of the
  org's at-risk accounts multiplied by the projected save rate.

The headline ``outcomes`` object keeps the ``/eval`` contract exactly:
``{kpi, baseline, projected, unit}``.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

# Manual-baseline reference points (what a CSM team hits without the platform).
_BASELINE_ACCEPTANCE = 0.55
_BASELINE_NRR = 102.0            # percent
_BASELINE_CHURN = 8.0           # percent (gross logo churn)
_BASELINE_SAVE_RATE = 0.30      # share of at-risk ARR saved by manual triage
_BASELINE_TIME_TO_ACTION_H = 72.0   # hours from signal to action
_PLATFORM_TIME_TO_ACTION_H = 6.0    # hours from signal to action

# How much of an action's estimated NRR impact is realised once accepted.
_REALISATION_FACTOR = 0.6

# Risk levels that count as "at risk" when summing addressable ARR.
_AT_RISK_LEVELS = {"high", "critical"}


def _parse_impact_points(estimate: str) -> float:
    """Extract the leading signed delta from an estimate string.

    Estimates look like ``"+4.8 index_0_100 over 90 days"`` or ``"+5.1 percent
    over 90 days"``; only the first number is the projected delta. Averaging
    every number would fold in unit tokens ("0_100") and the horizon ("90
    days") and wildly inflate the projection, so we take the first match only.
    """

    match = re.search(r"[-+]?\d+(?:\.\d+)?", estimate or "")
    return float(match.group()) if match else 0.0


async def _live_acceptance(org_id: str) -> Optional[Tuple[int, int]]:
    """Real (accepted_like, decided) counts from the ORG's recorded episodes.

    Scoped to ``org_id``: seeded day-zero episodes carry no ``org_id`` and belong
    to the Demo org, so an unscoped episode counts only for the demo tenant. Every
    other org sees only the decisions it produced. Returns ``None`` when the org
    has no decided episode yet, so callers fall back to a confidence-based
    projection instead of a fabricated decision log.
    """

    try:
        from app.api._org import DEMO_ORG
        from app.memory import get_memory  # type: ignore
        from app.memory.types import ACCEPTED_LIKE

        memory = get_memory()
        await memory._ensure_db()
        episodes = memory.all_episodes()
    except Exception:
        return None

    decided = 0
    accepted = 0
    for ep in episodes:
        if (getattr(ep, "org_id", None) or DEMO_ORG) != org_id:
            continue
        outcome = getattr(ep, "outcome", None)
        if outcome is None or outcome.decision == "pending":
            continue
        decided += 1
        if outcome.decision in ACCEPTED_LIKE:
            accepted += 1
    if decided == 0:
        return None
    return accepted, decided


def _avg_confidence(records: List[Dict[str, Any]]) -> float:
    scores = [
        (rec.get("recommendation") or {}).get("confidence", {}).get("score", 0.0)
        for rec in records
    ]
    scores = [s for s in scores if isinstance(s, (int, float))]
    return sum(scores) / len(scores) if scores else 0.7


def _avg_impact_points(records: List[Dict[str, Any]]) -> float:
    points = [
        _parse_impact_points(
            (rec.get("recommendation") or {}).get("expected_impact", {}).get("estimate", "")
        )
        for rec in records
    ]
    points = [p for p in points if p > 0]
    return sum(points) / len(points) if points else 5.0


async def _arr_at_risk(org_id: str) -> Tuple[float, int, int]:
    """At-risk ARR of the accounts owned by ``org_id``.

    Loads the org's own accounts (DB-backed, with the Demo org falling back to
    the seed corpus exactly like the accounts API) instead of the global seed, so
    a brand-new empty org returns ``(0.0, 0, 0)`` rather than the seed numbers.
    Returns ``(total_arr_at_risk, at_risk_account_count, total_account_count)``.
    """

    try:
        from app.api.accounts import _org_accounts  # type: ignore

        accounts = await _org_accounts(org_id, None)
    except Exception:
        return 0.0, 0, 0

    total = 0.0
    at_risk = 0
    for acc in accounts:
        level = str(acc.get("risk_level", "")).lower()
        if level in _AT_RISK_LEVELS:
            total += float(acc.get("arr", 0) or 0)
            at_risk += 1
    return round(total, 2), at_risk, len(accounts)


async def compute_outcomes(
    records: List[Dict[str, Any]],
    org_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Return (outcome_suite, outcomes_headline, full_breakdown) for ``org_id``.

    ``outcomes_headline`` matches the /eval contract:
    ``{kpi, baseline, projected, unit}``. Everything here is a labeled
    projection: baseline (manual triage) versus a platform projection derived
    from the simulator estimates, the engine's confidence, and the ORG's real
    acceptance, sized by the ORG's own at-risk ARR.

    A brand-new org with no accounts AND no decisions gets an honest empty
    headline: ``projected`` equals ``baseline``, ARR addressed is 0, and a
    ``no_data`` flag is set, rather than the seed corpus numbers.
    """

    live = await _live_acceptance(org_id)
    arr_at_risk, at_risk_accounts, total_accounts = await _arr_at_risk(org_id)
    avg_conf = _avg_confidence(records)
    avg_points = _avg_impact_points(records)

    # Honest empty state: the org owns no accounts and has decided nothing yet.
    no_data = live is None and total_accounts == 0

    if live is not None:
        accepted, decided = live
        accept_rate = accepted / decided if decided else 0.0
        adoption = accept_rate
        accept_source = "memory"
    else:
        accepted, decided = 0, 0
        accept_rate = 0.0
        # No real decisions yet: use the engine's own confidence as the expected
        # adoption factor for the projection rather than a fabricated decision log.
        adoption = avg_conf
        accept_source = "projection"

    if no_data:
        # No accounts and no decisions: project nothing. Baseline is shown as-is
        # and the projection equals it, so the org never sees seed numbers.
        adoption = 0.0
        accept_source = "no_data"
        projected_lift = 0.0
        projected_nrr = _BASELINE_NRR
        projected_churn = _BASELINE_CHURN
        projected_save_rate = _BASELINE_SAVE_RATE
        save_rate_lift = 0.0
        arr_addressed = 0.0
    else:
        # Projected NRR lift: average per-account impact, realised on the adopted
        # share, discounted by confidence and a realisation factor.
        projected_lift = avg_points * adoption * avg_conf * _REALISATION_FACTOR
        projected_nrr = round(_BASELINE_NRR + projected_lift, 1)

        # Churn reduction tracks inversely with the retention lift.
        projected_churn = round(max(0.0, _BASELINE_CHURN - projected_lift * 0.8), 1)

        # Save rate improves with adoption and confidence; capped to a max.
        projected_save_rate = round(
            min(0.85, _BASELINE_SAVE_RATE + 0.5 * adoption * avg_conf), 3
        )

        # Dollar value: the org's at-risk ARR multiplied by the save-rate lift.
        save_rate_lift = max(0.0, projected_save_rate - _BASELINE_SAVE_RATE)
        arr_addressed = round(arr_at_risk * save_rate_lift, 2)

    kpis = [
        {
            "kpi": "Net Revenue Retention",
            "unit": "percent",
            "baseline": _BASELINE_NRR,
            "projected": projected_nrr,
            "improved": projected_nrr > _BASELINE_NRR,
            "projected_label": True,
        },
        {
            "kpi": "Gross Churn Rate",
            "unit": "percent",
            "baseline": _BASELINE_CHURN,
            "projected": projected_churn,
            "improved": projected_churn < _BASELINE_CHURN,
            "projected_label": True,
        },
        {
            "kpi": "At-risk Save Rate",
            "unit": "ratio",
            "baseline": _BASELINE_SAVE_RATE,
            "projected": projected_save_rate,
            "improved": projected_save_rate > _BASELINE_SAVE_RATE,
            "projected_label": True,
        },
        {
            "kpi": "Time to Action",
            "unit": "hours",
            "baseline": _BASELINE_TIME_TO_ACTION_H,
            "projected": _PLATFORM_TIME_TO_ACTION_H,
            "improved": _PLATFORM_TIME_TO_ACTION_H < _BASELINE_TIME_TO_ACTION_H,
            "projected_label": True,
        },
        {
            "kpi": "Recommendation Acceptance",
            "unit": "ratio",
            "baseline": _BASELINE_ACCEPTANCE,
            "projected": round(accept_rate, 3) if accept_source == "memory" else None,
            "improved": accept_rate >= _BASELINE_ACCEPTANCE,
            "projected_label": accept_source != "memory",
            "measured": accept_source == "memory",
        },
    ]

    scored = [k for k in kpis if k["projected"] is not None]
    improved = sum(1 for k in scored if k["improved"])
    total = len(scored)
    suite = {
        "name": "Outcome Lift",
        "metric": "kpis_improved",
        "score": round(improved / total, 3) if total else 0.0,
        "passed": improved,
        "total": total,
        "healthy": improved == total,
    }

    headline = {
        "kpi": "Net Revenue Retention",
        "baseline": _BASELINE_NRR,
        "projected": projected_nrr,
        "unit": "percent",
        "no_data": no_data,
    }

    method = (
        "No accounts and no decisions for this org yet: baseline shown, projection "
        "equals baseline until the org has data."
        if no_data
        else (
            "Projection: simulator per-action impact across this org's accounts, "
            "weighted by engine confidence and the org's real human acceptance. "
            "Baseline is a manual-triage reference, not a measured control."
        )
    )
    breakdown = {
        "projected": True,
        "no_data": no_data,
        "method": method,
        "acceptance": {
            "accepted": accepted,
            "decided": decided,
            "rate": round(accept_rate, 3),
            "baseline_rate": _BASELINE_ACCEPTANCE,
            "source": accept_source,
            "measured": accept_source == "memory",
        },
        "arr_at_risk": {
            "total": arr_at_risk,
            "accounts": at_risk_accounts,
            "addressed": arr_addressed,
            "baseline_save_rate": _BASELINE_SAVE_RATE,
            "projected_save_rate": projected_save_rate,
            "unit": "usd",
            "projected": True,
        },
        "avg_confidence": round(avg_conf, 3),
        "avg_impact_points": round(avg_points, 2),
        "adoption_factor": round(adoption, 3),
        "kpis": kpis,
    }
    return suite, headline, breakdown


async def evaluate(org_id: Optional[str] = None) -> Dict[str, Any]:
    """Run the outcome suite standalone and return suite + headline + breakdown.

    Defaults to the Demo org so a manual run shows the seeded corpus numbers.
    """

    from app.api._org import DEMO_ORG
    from app.eval.scenario import load_golden, run_cases

    records = await run_cases(load_golden())
    suite, headline, breakdown = await compute_outcomes(records, org_id or DEMO_ORG)
    return {"suite": suite, "outcomes": headline, "breakdown": breakdown}


if __name__ == "__main__":  # pragma: no cover - manual invocation
    result = asyncio.run(evaluate())
    suite = result["suite"]
    print(
        f"{suite['name']:<22} {suite['metric']:<14} "
        f"score={suite['score']:.3f} passed={suite['passed']}/{suite['total']}"
    )
    print("outcomes:", result["outcomes"])
    print("acceptance:", result["breakdown"]["acceptance"])
    print("arr_at_risk:", result["breakdown"]["arr_at_risk"])
