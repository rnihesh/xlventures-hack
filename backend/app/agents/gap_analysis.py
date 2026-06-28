"""Missing-information analysis (PDF workflow step 3).

Names the concrete facts the run does NOT yet know. It is consumed by the
first-class ``gap_analysis`` graph node, which uses the result to (a) record the
gaps on state for the recommendation and critic, and (b) decide whether to loop
back to retrieval for more grounding.

On prod (an OpenAI key is configured) the gaps are identified by the model,
grounded in the actual signal, retrieved evidence, decision point, and account,
so they reflect what THIS run is genuinely missing. Offline (DEMO_MODE, no key)
or if the model call fails, it falls back to the deterministic keyword-coverage
analysis the explanation layer uses (``app.explain.recommendation.
_missing_information``), so the run never breaks and the gaps surfaced here stay
aligned with the ones rendered on the recommendation object. Either way the
return shape and keys are identical, including the criticality split and the
gap-to-query mapping that drive the clarify loop.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Match the explanation layer's cap so the model and deterministic paths surface
# the same number of gaps at most.
_MAX_GAPS = 4

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


async def analyze_gaps(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return the missing-information analysis for the current run state.

    Output shape::

        {
            "missing_information": [{gap, why_it_matters, suggested_source}, ...],
            "information_gaps": ["<gap>", ...],
            "critical_gaps": ["<gap>", ...],   # subset that are high-impact
        }

    On prod the model names the gaps grounded in the actual context; offline or
    on any failure it falls back to the deterministic analysis below.
    """

    from app.demo import demo_mode_enabled

    if not demo_mode_enabled():
        try:
            llm_result = await _llm_gaps(state)
        except Exception:  # noqa: BLE001 - never break the run on the model call
            llm_result = None
        if llm_result is not None:
            return llm_result

    return _analyze_gaps_deterministic(state)


async def _llm_gaps(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ask the model which facts are genuinely missing, grounded in the context.

    Returns the analysis dict, or None when the model produced nothing usable so
    the caller falls back to the deterministic analysis.
    """

    import json

    from app.deps import get_llm

    signal = state.get("signal") or {}
    signal_content = signal.get("content", "")
    evidence = state.get("evidence") or []
    ev_text = (
        "\n".join(
            f"- {(e.get('text') or e.get('snippet') or '')[:280]}"
            for e in evidence[:8]
            if isinstance(e, dict)
        )
        if isinstance(evidence, list)
        else ""
    ) or "none"
    decision_point = state.get("decision_point", "renewal_risk")
    account_id = state.get("account_id", "unknown-account")

    prompt = (
        "You are the missing-information analyst for an account decision. Read the "
        "signal and the cited evidence, then name the concrete facts the engine "
        "would need to commit confidently but that the evidence does NOT cover. "
        "Ground every gap in what is actually absent from the evidence below, not a "
        "fixed checklist. If the evidence is sufficient, return an empty list.\n\n"
        f"Decision point: {decision_point}\n"
        f"Account: {account_id}\n"
        f"Signal: {signal_content}\n\n"
        f"Retrieved evidence:\n{ev_text}\n\n"
        f"Return STRICT JSON with at most {_MAX_GAPS} gaps: "
        '{"gaps": [{"gap": "<short title of the missing fact>", '
        '"why_it_matters": "<one sentence on why this fact would change the call>", '
        '"suggested_source": "<where to get it, e.g. CRM or Support system>", '
        '"critical": <true if this fact is high-impact enough to pause and gather '
        'before recommending, else false>}]}.'
    )

    resp = await get_llm(temperature=0).ainvoke(prompt)
    text = getattr(resp, "content", "") or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    data = json.loads(text[start : end + 1])

    missing: List[Dict[str, Any]] = []
    information_gaps: List[str] = []
    critical: List[str] = []
    for item in data.get("gaps") or []:
        if not isinstance(item, dict):
            continue
        gap = str(item.get("gap") or item.get("label") or item.get("title") or "").strip()
        if not gap:
            continue
        why = str(item.get("why_it_matters") or item.get("why") or "").strip()
        source = str(item.get("suggested_source") or item.get("source") or "").strip()
        missing.append(
            {"gap": gap, "why_it_matters": why, "suggested_source": source}
        )
        information_gaps.append(gap)
        if bool(item.get("critical")):
            critical.append(gap)
        if len(missing) >= _MAX_GAPS:
            break

    if not missing:
        # An explicit "no gaps" verdict is valid: evidence is sufficient.
        if isinstance(data.get("gaps"), list):
            return {
                "missing_information": [],
                "information_gaps": [],
                "critical_gaps": [],
            }
        return None

    return {
        "missing_information": missing,
        "information_gaps": information_gaps,
        "critical_gaps": critical,
    }


def _analyze_gaps_deterministic(state: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic, offline gap analysis (fallback).

    Reuses the explanation layer's coverage analysis so the gaps named here and
    the gaps rendered on the recommendation never drift apart. The same state
    always yields the same gaps.
    """

    signal = state.get("signal") or {}
    signal_content = signal.get("content", "")
    evidence = state.get("evidence") or []

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
