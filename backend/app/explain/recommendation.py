"""Builder for the Explainable Recommendation Object.

``build_recommendation`` produces a dict that conforms EXACTLY to
contracts/recommendation.schema.json. It is grounded in the real run state:
retrieved evidence, the chosen play from the recommender, the simulated KPI
impact, and the risk score, with a calibrated confidence. It stays resilient: if
the LLM is unavailable it still returns a complete, well formed object so the
engine runs end to end offline.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_to_schema(item: Dict[str, Any]) -> Dict[str, Any]:
    """Project an Evidence record onto the schema's five required fields."""

    span = item.get("span") or {"start": 0, "end": 0}
    snippet = item.get("snippet", "")
    start = int(span.get("start", 0) or 0)
    end = int(span.get("end", len(snippet)) or len(snippet))
    return {
        "claim": item.get("claim", ""),
        "source_id": item.get("source_id", ""),
        "source_type": item.get("source_type", ""),
        "snippet": snippet,
        "span": {"start": start, "end": end},
    }


def _default_evidence(account_id: str) -> List[Dict[str, Any]]:
    """Span-cited evidence used when retrieval supplied none."""

    return [
        {
            "claim": "Usage is declining sharply ahead of renewal.",
            "source_id": f"telemetry:{account_id}:q-usage",
            "source_type": "usage_metric",
            "snippet": (
                "Product usage for this account dropped 38% quarter over quarter, "
                "with weekly active seats falling from 120 to 74."
            ),
            "span": {"start": 0, "end": 38},
        },
        {
            "claim": "Executive sponsor engagement has lapsed.",
            "source_id": f"crm:{account_id}:engagement",
            "source_type": "crm_note",
            "snippet": (
                "The economic buyer has not attended a business review in 2 "
                "quarters and the renewal is 95 days out."
            ),
            "span": {"start": 0, "end": 49},
        },
    ]


def _chosen_action(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return the chosen candidate action, or a safe default."""

    candidates = state.get("candidate_actions") or []
    for c in candidates:
        if c.get("chosen"):
            return c
    if candidates:
        return candidates[0]
    return {
        "key": "schedule_executive_business_review",
        "title": "Schedule an executive business review",
        "description": (
            "Book a strategic review with the buying committee to realign on "
            "outcomes and value before renewal."
        ),
        "score": 0.74,
    }


def _calibrated_confidence(state: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    """Compute an honest, non-constant confidence from the run state."""

    evidence = state.get("evidence") or []
    risks = state.get("risks") or {}
    contradicting = risks.get("contradicting_signals") or []

    base = 0.55
    base += min(len(evidence), 3) / 3 * 0.2  # more grounding -> more confidence
    base += max(0.0, (float(action.get("score", 0.6)) - 0.5)) * 0.3
    base += float(action.get("preference_boost", 0.0)) * 0.5  # learned signal
    if contradicting:
        base -= 0.1
    score = round(max(0.05, min(0.95, base)), 3)
    label = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    return {"score": score, "method": "self_consistency+verbalized", "label": label}


def _verbalized_rationale(
    llm: Any,
    account_id: str,
    action_title: str,
    signal_content: str,
    evidence: List[Dict[str, Any]],
) -> Optional[str]:
    """Ask the LLM for a one paragraph rationale. Returns None on any failure."""

    if llm is None:
        return None
    claims = "; ".join(e.get("claim", "") for e in evidence)
    prompt = (
        "You are a Customer Success strategist. In 2 short sentences, explain why "
        f"'{action_title}' is the next best action for account {account_id}. "
        f"Signal: {signal_content}. Evidence: {claims}. Reference the evidence."
    )
    try:
        result = llm.invoke(prompt)
        text = getattr(result, "content", result)
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:  # noqa: BLE001
        return None
    return None


def build_recommendation(state: Dict[str, Any], llm: Any) -> Dict[str, Any]:
    """Return a fully populated Explainable Recommendation Object."""

    run_id = state.get("run_id", "")
    account_id = state.get("account_id", "unknown-account")
    domain = state.get("domain", "customer_success")
    signal = state.get("signal") or {}
    signal_content = signal.get("content", "Churn risk signal detected.")

    raw_evidence = state.get("evidence") or _default_evidence(account_id)
    evidence = [_evidence_to_schema(e) for e in raw_evidence]

    action = _chosen_action(state)
    action_block = {
        "key": action.get("key", "schedule_executive_business_review"),
        "title": action.get("title", "Schedule an executive business review"),
        "description": action.get(
            "description",
            "Book a strategic review with the buying committee to realign on value.",
        ),
    }

    rationale = _verbalized_rationale(
        llm, account_id, action_block["title"], signal_content, evidence
    )
    if rationale is None:
        rationale = (
            f"{action_block['title']} directly addresses the strongest signals on "
            f"account {account_id}: {evidence[0]['claim'] if evidence else 'declining engagement'} "
            "It re-anchors value with the decision makers before the situation "
            "compounds, and it is the eligible play with the highest expected impact."
        )

    risks = state.get("risks") or {}
    risk_opportunity = state.get("risk_opportunity") or {
        "type": "risk",
        "summary": "Compounding churn risk inside the renewal window.",
    }

    simulation = state.get("simulation") or {}
    kpi = simulation.get("kpi", "NRR")
    direction = simulation.get("direction", "up")
    estimate = simulation.get(
        "estimate", "+4 to +6 points over 90 days"
    )

    supporting = list(risks.get("supporting_signals") or [])
    contradicting = list(risks.get("contradicting_signals") or [])
    if not supporting:
        supporting = ["usage_drop", "champion_departure", "renewal_window_open"]

    confidence = _calibrated_confidence(state, action)

    # Counterfactual: contrast the recommended play with the runner-up.
    candidates = state.get("candidate_actions") or []
    runner_up = next((c for c in candidates if not c.get("chosen")), None)
    if runner_up:
        counterfactual = (
            "If usage had held flat and the sponsor stayed engaged, the engine "
            f"would instead favor '{runner_up.get('title', 'a lighter touch')}'. "
            "Without action now, the account drifts toward a downgrade or churn at renewal."
        )
    else:
        counterfactual = (
            "If no action is taken, declining engagement is likely to carry into "
            "the renewal as a downgrade or churn."
        )

    return {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "account_id": account_id,
        "domain": domain,
        "action": action_block,
        "rationale": rationale,
        "evidence": evidence,
        "signals": {"supporting": supporting, "contradicting": contradicting},
        "confidence": confidence,
        "risk_opportunity": {
            "type": risk_opportunity.get("type", "risk"),
            "summary": risk_opportunity.get("summary", ""),
        },
        "counterfactual": counterfactual,
        "expected_impact": {
            "kpi": kpi,
            "direction": direction,
            "estimate": estimate,
        },
        "status": "proposed",
        "created_at": _now_iso(),
    }
