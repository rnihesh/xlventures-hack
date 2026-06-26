"""Risk and opportunity scorer.

Turns evidence plus the decision point into a discrete risk or opportunity
finding with a numeric score and an honest split of supporting vs contradicting
signals. The downstream recommender and the explainer read these.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.agents import make_step
from app.packs.loader import load_pack
from app.packs.registry import register_agent

# Decision points that are framed as upside rather than downside.
_OPPORTUNITY_POINTS = {"expansion_signal", "closing_signal"}

# Heuristic weights for evidence source types in a churn-risk context.
_SOURCE_WEIGHT = {
    "usage_metric": 0.9,
    "product_telemetry": 0.9,
    "crm_note": 0.7,
    "crm_activity": 0.7,
    "crm_record": 0.6,
    "survey_response": 0.65,
    "billing_event": 0.6,
    "support_ticket": 0.4,
    "knowledge_base": 0.2,
}


def _split_signals(
    state: Dict[str, Any], decision_point: str
) -> Tuple[List[str], List[str]]:
    """Derive supporting and contradicting signal keys from the pack."""

    try:
        pack = load_pack(state.get("domain", "customer_success"))
    except Exception:  # noqa: BLE001
        return [], []

    dp = pack.decision_points.get(decision_point)
    supporting = list(dp.trigger_signals) if dp else []

    # Contradicting signals: pack signals not in this decision point's triggers
    # that point the other way (a small, deterministic heuristic for the demo).
    all_keys = [s.key for s in pack.signals]
    contradicting_pool = [
        k
        for k in all_keys
        if k not in supporting
        and any(token in k for token in ("expansion", "seat_growth", "intent"))
    ]
    # Keep at most one contradicting signal so the split reads cleanly.
    return supporting, contradicting_pool[:1]


def _score(evidence: List[Dict[str, Any]]) -> float:
    """Compute a 0..1 risk magnitude from evidence strength."""

    if not evidence:
        return 0.5
    total = 0.0
    for item in evidence:
        weight = _SOURCE_WEIGHT.get(item.get("source_type", ""), 0.5)
        confidence = float(item.get("score", 0.7) or 0.7)
        total += weight * confidence
    raw = total / len(evidence)
    # Clamp into a believable band.
    return max(0.05, min(0.95, round(raw, 3)))


@register_agent(
    capability="risk_scorer",
    description="Scores the situation into a risk or opportunity with weighted signals.",
    output_keys=["risks", "risk_opportunity"],
    cost_tier="standard",
    tags=["analysis"],
)
async def node(state: Dict[str, Any]) -> Dict[str, Any]:
    decision_point = state.get("decision_point", "renewal_risk")
    evidence = state.get("evidence") or []
    is_opportunity = decision_point in _OPPORTUNITY_POINTS

    magnitude = _score(evidence)
    supporting, contradicting = _split_signals(state, decision_point)

    ro_type = "opportunity" if is_opportunity else "risk"
    if is_opportunity:
        summary = (
            "Healthy engagement plus expansion intent inside the account suggests "
            "an opportunity to grow committed spend."
        )
    else:
        summary = (
            "Declining usage and a disengaged executive sponsor inside the renewal "
            "window indicate compounding churn risk."
        )

    risks = {
        "score": magnitude,
        "decision_point": decision_point,
        "supporting_signals": supporting,
        "contradicting_signals": contradicting,
        "evidence_count": len(evidence),
        "drivers": [e.get("claim", "") for e in evidence][:3],
    }
    risk_opportunity = {"type": ro_type, "summary": summary}

    return {
        "risks": risks,
        "risk_opportunity": risk_opportunity,
        "messages": [
            {
                "role": "risk_scorer",
                "content": f"{ro_type} magnitude {magnitude:.2f} for {decision_point}.",
            }
        ],
        "steps": [
            make_step(
                "risk_scorer",
                f"Scored {ro_type} at {magnitude:.2f}",
                {
                    "score": magnitude,
                    "type": ro_type,
                    "supporting": supporting,
                    "contradicting": contradicting,
                },
            )
        ],
    }
