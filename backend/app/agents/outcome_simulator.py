"""Outcome simulator.

Projects the KPI movement of the chosen play against the decision point's
primary KPI. Produces a baseline, a projected value, and a signed delta so the
UI can show a measurable, money-adjacent outcome.
"""

from __future__ import annotations

from typing import Any, Dict

from app.agents import make_step
from app.packs.loader import load_pack
from app.packs.registry import register_agent

# Per-KPI baseline and a believable lift band when the chosen play lands.
_KPI_MODEL = {
    "NRR": {"baseline": 104.0, "unit": "percent", "direction": "up", "lift": 5.0},
    "GRR": {"baseline": 88.0, "unit": "percent", "direction": "up", "lift": 4.0},
    "churn_rate": {"baseline": 11.0, "unit": "percent", "direction": "down", "lift": 3.5},
    "health_score": {"baseline": 58.0, "unit": "index_0_100", "direction": "up", "lift": 9.0},
    "time_to_value": {"baseline": 42.0, "unit": "days", "direction": "down", "lift": 12.0},
    "win_rate": {"baseline": 22.0, "unit": "percent", "direction": "up", "lift": 6.0},
    "pipeline_velocity": {"baseline": 100.0, "unit": "index", "direction": "up", "lift": 14.0},
    "outcome_score": {"baseline": 60.0, "unit": "index_0_100", "direction": "up", "lift": 8.0},
}


def _chosen(state: Dict[str, Any]) -> Dict[str, Any]:
    candidates = state.get("candidate_actions") or []
    for c in candidates:
        if c.get("chosen"):
            return c
    return candidates[0] if candidates else {}


@register_agent(
    capability="outcome_simulator",
    description="Projects KPI impact (baseline, projected, delta) for the chosen play.",
    output_keys=["simulation"],
    cost_tier="standard",
    tags=["analysis"],
)
async def node(state: Dict[str, Any]) -> Dict[str, Any]:
    domain = state.get("domain", "customer_success")
    decision_point = state.get("decision_point", "renewal_risk")
    risk_score = float((state.get("risks") or {}).get("score", 0.6))

    pack = load_pack(domain)
    dp = pack.decision_points.get(decision_point)
    kpi_key = dp.primary_kpi if dp else "outcome_score"
    model = _KPI_MODEL.get(kpi_key, _KPI_MODEL["outcome_score"])

    chosen = _chosen(state)
    play_value = float(chosen.get("score", 0.6))

    # Scale the lift by how confident and decisive the chosen play is, and by
    # how acute the risk is (more headroom to recover).
    effectiveness = max(0.2, min(1.0, 0.5 * play_value + 0.5 * risk_score))
    if chosen.get("key") == "monitor_no_action":
        effectiveness *= 0.25

    delta = round(model["lift"] * effectiveness, 1)
    baseline = model["baseline"]
    if model["direction"] == "up":
        projected = round(baseline + delta, 1)
        estimate = f"+{delta} {model['unit']} over 90 days"
    else:
        projected = round(baseline - delta, 1)
        estimate = f"-{delta} {model['unit']} over 90 days"

    simulation = {
        "kpi": kpi_key,
        "unit": model["unit"],
        "direction": model["direction"],
        "baseline": baseline,
        "projected": projected,
        "delta": delta,
        "estimate": estimate,
        "effectiveness": round(effectiveness, 3),
        "play_key": chosen.get("key"),
    }

    return {
        "simulation": simulation,
        "messages": [
            {
                "role": "outcome_simulator",
                "content": f"Projected {kpi_key} {model['direction']} by {delta} {model['unit']}.",
            }
        ],
        "steps": [
            make_step(
                "outcome_simulator",
                f"Projected {kpi_key}: {baseline} -> {projected} {model['unit']}",
                simulation,
            )
        ],
    }
