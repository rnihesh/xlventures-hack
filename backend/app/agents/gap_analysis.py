"""Missing-information analysis (PDF workflow step 3).

A small, deterministic, offline helper that names the concrete facts the run
does NOT yet know. It is consumed by the first-class ``gap_analysis`` graph node,
which uses the result to (a) record the gaps on state for the recommendation and
critic, and (b) decide whether to loop back to retrieval for more grounding.

The gap logic deliberately reuses the same keyword-coverage analysis the
explanation layer uses (``app.explain.recommendation._missing_information``), so
the gaps surfaced here are identical to the ones rendered on the recommendation
object. This module only adds the criticality split and the gap-to-query mapping
that drive the clarify loop, keeping the orchestration concerns inside the graph
layer it owns.
"""

from __future__ import annotations

from typing import Any, Dict, List

# The high-impact gaps: when several of these are open at once, the engine is
# reasoning with too little to commit, so the clarify loop re-retrieves first.
_CRITICAL_GAPS = {
    "No recent product usage data",
    "Renewal date and timeline unknown",
    "No executive sponsor identified",
}

# Targeted retrieval sub-queries for each gap, used when the clarify loop fires.
# Each query is phrased to surface the specific missing fact on a re-retrieve.
_GAP_QUERIES: Dict[str, str] = {
    "No recent product usage data": "product usage adoption telemetry active seats logins trend",
    "Renewal date and timeline unknown": "renewal date contract term expiry timeline window",
    "No executive sponsor identified": "executive sponsor champion stakeholder economic buyer",
    "Support and incident history not available": "support tickets incidents escalations CSAT",
    "Account value (ARR) not in context": "account ARR contract value revenue tier plan",
    "No signal on competitive pressure": "competitor competitive evaluation alternative vendor switch",
}


def analyze_gaps(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return the missing-information analysis for the current run state.

    Output shape::

        {
            "missing_information": [{gap, why_it_matters, suggested_source}, ...],
            "information_gaps": ["<gap>", ...],
            "critical_gaps": ["<gap>", ...],   # subset that are high-impact
        }

    Deterministic and offline: the same state always yields the same gaps.
    """

    signal = state.get("signal") or {}
    signal_content = signal.get("content", "")
    evidence = state.get("evidence") or []

    # Reuse the explanation layer's coverage analysis so the gaps named here and
    # the gaps rendered on the recommendation never drift apart.
    try:
        from app.explain.recommendation import _missing_information

        missing = _missing_information(state, evidence, signal_content)
    except Exception:  # noqa: BLE001 - never break the run on the analysis
        missing = []

    information_gaps = [str(item.get("gap", "")) for item in missing if item.get("gap")]
    critical = [g for g in information_gaps if g in _CRITICAL_GAPS]

    return {
        "missing_information": missing,
        "information_gaps": information_gaps,
        "critical_gaps": critical,
    }


def gap_targeted_queries(critical_gaps: List[str]) -> List[str]:
    """Map critical gaps to retrieval sub-queries for the clarify loop."""

    queries: List[str] = []
    for gap in critical_gaps:
        query = _GAP_QUERIES.get(gap)
        if query and query not in queries:
            queries.append(query)
    return queries
