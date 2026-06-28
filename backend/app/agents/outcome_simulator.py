"""Outcome simulator.

Projects the KPI movement of the chosen play against the decision point's
primary KPI. Produces a baseline, a projected value, and a signed delta so the
UI can show a measurable, money-adjacent outcome.

On prod (an OpenAI key is configured) the projection is model driven: the model
reads the actual signal, the cited evidence, the chosen play, the decision point
and the risk score, then returns a grounded before/after for the primary KPI.
The deterministic formula below is kept ONLY as the offline fallback (no key) or
when the model call fails, so a run never breaks.
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

# Units whose values are percentages and must stay within 0..100.
_PERCENT_UNITS = {"percent", "index_0_100"}


def _chosen(state: Dict[str, Any]) -> Dict[str, Any]:
    candidates = state.get("candidate_actions") or []
    for c in candidates:
        if c.get("chosen"):
            return c
    return candidates[0] if candidates else {}


def _effectiveness(state: Dict[str, Any], chosen: Dict[str, Any], risk_score: float) -> float:
    """How confident and decisive the chosen play is, scaled by risk headroom."""

    play_value = float(chosen.get("score", 0.6))
    effectiveness = max(0.2, min(1.0, 0.5 * play_value + 0.5 * risk_score))
    if chosen.get("key") == "monitor_no_action":
        effectiveness *= 0.25
    return effectiveness


def _build_simulation(
    kpi_key: str,
    model: Dict[str, Any],
    baseline: float,
    projected: float,
    effectiveness: float,
    play_key: Any,
    basis: str | None = None,
) -> Dict[str, Any]:
    """Assemble the simulation dict in the exact shape the UI and recommendation read."""

    delta = round(abs(projected - baseline), 1)
    sign = "+" if projected >= baseline else "-"
    estimate = f"{sign}{delta} {model['unit']} over 90 days"
    simulation: Dict[str, Any] = {
        "kpi": kpi_key,
        "unit": model["unit"],
        "direction": model["direction"],
        "baseline": round(baseline, 1),
        "projected": round(projected, 1),
        "delta": delta,
        "estimate": estimate,
        "effectiveness": round(effectiveness, 3),
        "play_key": play_key,
    }
    if basis:
        simulation["basis"] = basis
    return simulation


def _deterministic_simulation(
    kpi_key: str,
    model: Dict[str, Any],
    effectiveness: float,
    play_key: Any,
) -> Dict[str, Any]:
    """The original fixed-formula projection, kept as the offline fallback."""

    delta = round(model["lift"] * effectiveness, 1)
    baseline = model["baseline"]
    if model["direction"] == "up":
        projected = round(baseline + delta, 1)
    else:
        projected = round(baseline - delta, 1)
    return _build_simulation(kpi_key, model, baseline, projected, effectiveness, play_key)


async def _llm_simulation(
    state: Dict[str, Any],
    kpi_key: str,
    model: Dict[str, Any],
    decision_point: str,
    risk_score: float,
    effectiveness: float,
    play_key: Any,
) -> Dict[str, Any] | None:
    """The model projects the KPI movement from the actual context.

    Returns a simulation dict in the same shape as the deterministic path, or
    None offline (no key) or on any failure so the formula fallback is used.
    """
    from app.demo import demo_mode_enabled

    if demo_mode_enabled():
        return None
    import json

    from app.deps import get_llm

    signal = (state.get("signal") or {}).get("content", "")
    evidence = state.get("evidence") or []
    ev_text = (
        "\n".join(
            f"- {(e.get('text') or e.get('snippet') or '')[:280]}"
            for e in evidence[:6]
            if isinstance(e, dict)
        )
        if isinstance(evidence, list)
        else ""
    ) or "none"

    chosen = _chosen(state)
    candidates = state.get("candidate_actions") or []
    play = (
        f"{chosen.get('key')}: {chosen.get('title')}. {chosen.get('description', '')}".strip()
        if chosen
        else "none"
    )
    other_plays = (
        ", ".join(str(c.get("key")) for c in candidates if not c.get("chosen")) or "none"
    )

    unit = model["unit"]
    direction = model["direction"]
    baseline_hint = model["baseline"]
    clamp_note = (
        " Keep both values between 0 and 100." if unit in _PERCENT_UNITS else ""
    )

    prompt = (
        "You are the outcome simulator for an account decision. Project how the "
        "primary KPI will move over the next 90 days if the chosen play is executed, "
        "grounded in the actual signal and cited evidence for THIS account.\n\n"
        f"Decision point: {decision_point}\n"
        f"Primary KPI: {kpi_key} (unit: {unit}, better when it moves {direction})\n"
        f"Typical baseline for this KPI: {baseline_hint} {unit}\n"
        f"Risk score (0 to 1, higher means more acute): {risk_score}\n"
        f"Signal: {signal}\n\n"
        f"Evidence:\n{ev_text}\n\n"
        f"Chosen play: {play}\n"
        f"Plays not chosen: {other_plays}\n\n"
        "Estimate a realistic CURRENT (before) value and a PROJECTED (after) value "
        "for the primary KPI if the chosen play lands. Move the KPI in the "
        f"{direction} direction by a credible, not exaggerated, amount.{clamp_note}\n\n"
        'Return STRICT JSON: {"kpi": "<primary KPI name>", "before": <number>, '
        '"after": <number>, "basis": "<one line, grounded in the evidence>"}.'
    )
    try:
        resp = await get_llm(temperature=0).ainvoke(prompt)
        text = getattr(resp, "content", "") or ""
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start : end + 1])
        baseline = float(data.get("before"))
        projected = float(data.get("after"))
    except Exception:  # noqa: BLE001 - fall back to the deterministic formula
        return None

    basis = str(data.get("basis") or "").strip()
    if unit in _PERCENT_UNITS:
        baseline = max(0.0, min(100.0, baseline))
        projected = max(0.0, min(100.0, projected))

    # Tie effectiveness to the projected movement so the consumer (projected NRR
    # in run generation) still gets a sane, grounded confidence proxy.
    lift = model.get("lift") or 0.0
    if lift > 0:
        effectiveness = max(0.0, min(1.0, abs(projected - baseline) / lift))

    return _build_simulation(
        kpi_key, model, baseline, projected, effectiveness, play_key, basis=basis
    )


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
    play_key = chosen.get("key")
    effectiveness = _effectiveness(state, chosen, risk_score)

    # On prod the model projects the KPI movement from the actual evidence. The
    # deterministic formula is the offline fallback (no key) or on any failure.
    simulation = await _llm_simulation(
        state, kpi_key, model, decision_point, risk_score, effectiveness, play_key
    )
    if simulation is None:
        simulation = _deterministic_simulation(kpi_key, model, effectiveness, play_key)

    baseline = simulation["baseline"]
    projected = simulation["projected"]
    delta = simulation["delta"]

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
