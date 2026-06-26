"""Counterfactual "what-if" API.

Lets the UI nudge a couple of input signals (usage trend, NPS, contract size /
ARR) and re-run the decision pipeline to see how the recommendation and its
confidence change versus the baseline.

The endpoint reuses ``build_graph`` and the exact same node pipeline as a real
run: it seeds the graph with the account's context, invokes the graph once to
obtain the grounded baseline recommendation (chosen play, candidate set, risk
magnitude, calibrated confidence), then applies the user's overrides as a
deterministic counterfactual layer:

* the override numbers translate into a churn-risk *pressure*;
* the candidate plays produced by ``play_recommender`` are re-scored at the new
  risk magnitude (using the same scoring formula), which can flip the chosen
  action;
* confidence is re-calibrated from how strongly (and how coherently) the
  overridden signals point toward the recommended play.

Everything is synchronous JSON (no SSE) and fully offline-safe: every external
hop degrades to a deterministic fallback so the demo never blanks out.
"""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("app.api.whatif")

router = APIRouter(tags=["whatif"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class Overrides(BaseModel):
    """The signals a user may nudge. All optional; omitted ones keep baseline."""

    usage_trend: Optional[float] = Field(
        default=None, description="Quarter-over-quarter usage change, percent."
    )
    nps: Optional[float] = Field(default=None, description="Net promoter score, 0..10.")
    arr: Optional[float] = Field(default=None, description="Annual recurring revenue / contract size.")

    model_config = {"extra": "allow"}


class WhatIfIn(BaseModel):
    domain: str = "customer_success"
    account_id: str
    overrides: Overrides = Field(default_factory=Overrides)


# ---------------------------------------------------------------------------
# Baseline context resolution
# ---------------------------------------------------------------------------
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _baseline_context(account_id: str) -> Dict[str, Any]:
    """Derive a numeric baseline context for an account from the seed corpus.

    Falls back to neutral defaults when the account is unknown so the endpoint
    works for any id the UI sends.
    """

    account: Dict[str, Any] = {}
    try:
        from app.api.accounts import _BY_ID  # type: ignore

        account = _BY_ID.get(account_id, {}) or {}
    except Exception:  # noqa: BLE001 - accounts slice optional
        account = {}

    health = float(account.get("health_score", 60))
    arr = float(account.get("arr", 120000) or 0)
    # Map health onto plausible usage-trend and NPS baselines so the sliders
    # start from a number that matches the account's story.
    usage_trend = round((health - 70.0) * 0.8, 1)
    nps = round(_clamp(health / 10.0, 0.0, 10.0), 1)

    return {
        "usage_trend": usage_trend,
        "nps": nps,
        "arr": arr,
        "name": account.get("name", account_id),
        "last_signal": account.get(
            "last_signal", "Account health signal detected; renewal approaching."
        ),
    }


# ---------------------------------------------------------------------------
# Graph execution
# ---------------------------------------------------------------------------
async def _run_pipeline(domain: str, account_id: str, signal: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke the real planner graph once and return its final merged state."""

    from app.deps import get_checkpointer
    from app.graph.planner import build_graph

    run_id = f"whatif_{uuid.uuid4().hex[:12]}"
    initial_state = {
        "run_id": run_id,
        "domain": domain,
        "account_id": account_id,
        "signal": signal,
        "plan": [],
        "capabilities": [],
        "steps": [],
        "messages": [],
        "recommendation": None,
    }
    config = {"configurable": {"thread_id": run_id}}

    checkpointer = await get_checkpointer()
    graph = build_graph(checkpointer)
    final_state = await graph.ainvoke(initial_state, config=config)
    return dict(final_state or {})


# ---------------------------------------------------------------------------
# Counterfactual math
# ---------------------------------------------------------------------------
def _pressures(context: Dict[str, Any]) -> Dict[str, float]:
    """Translate overridden inputs into a churn-risk pressure in [-1, 1].

    Positive pressure means the inputs point toward higher churn risk; negative
    means a healthier, expansion-leaning picture.
    """

    usage_trend = float(context.get("usage_trend", 0.0))
    nps = float(context.get("nps", 7.0))

    # -40% usage => +1 pressure; +40% => -1 (growth).
    usage_pressure = _clamp(-usage_trend / 40.0, -1.0, 1.0)
    # NPS 0 => +1 pressure; NPS 10 => mild negative; neutral anchor at 7.
    nps_pressure = _clamp((7.0 - nps) / 7.0, -1.0, 1.0)

    mean_pressure = _clamp(0.6 * usage_pressure + 0.4 * nps_pressure, -1.0, 1.0)
    conflict = abs(usage_pressure - nps_pressure) / 2.0  # 0 aligned .. 1 opposed

    return {
        "usage_pressure": round(usage_pressure, 3),
        "nps_pressure": round(nps_pressure, 3),
        "mean_pressure": round(mean_pressure, 3),
        "conflict": round(conflict, 3),
    }


def _rescore_candidates(candidates: List[Dict[str, Any]], new_risk: float) -> List[Dict[str, Any]]:
    """Re-rank the recommender's candidates at the overridden risk magnitude.

    Mirrors the scoring used in ``play_recommender`` so the re-plan stays
    consistent with how the real graph ranks plays.
    """

    rescored: List[Dict[str, Any]] = []
    for cand in candidates:
        base = float(cand.get("base_value", cand.get("score", 0.5)))
        pref = float(cand.get("preference_boost", 0.0))
        epi = float(cand.get("episode_boost", 0.0))
        key = cand.get("key", "")
        risk_term = (new_risk - 0.5) * (-0.4 if key == "monitor_no_action" else 0.4)
        score = _clamp(round(base + risk_term + pref + epi, 3), 0.02, 0.99)
        item = dict(cand)
        item["score"] = score
        item["risk_term"] = round(risk_term, 3)
        item["chosen"] = False
        rescored.append(item)

    rescored.sort(key=lambda c: c["score"], reverse=True)
    if rescored:
        rescored[0]["chosen"] = True
    return rescored


def _label_for(score: float) -> str:
    return "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.post("/whatif")
async def whatif(body: WhatIfIn) -> Dict[str, Any]:
    """Re-plan with a couple of overridden inputs and report the delta."""

    domain = body.domain or "customer_success"
    account_id = body.account_id

    base_ctx = _baseline_context(account_id)
    overrides = body.overrides.model_dump(exclude_none=True)
    applied = {
        "usage_trend": float(overrides.get("usage_trend", base_ctx["usage_trend"])),
        "nps": float(overrides.get("nps", base_ctx["nps"])),
        "arr": float(overrides.get("arr", base_ctx["arr"])),
    }

    # Build a signal whose narrative reflects the (overridden) context so the
    # text-producing nodes ground their output in the what-if scenario.
    signal_content = (
        f"{base_ctx['last_signal']} "
        f"Usage trend {applied['usage_trend']:+.0f}% QoQ, "
        f"NPS {applied['nps']:.0f}/10, ARR ${applied['arr']:,.0f}."
    )
    signal = {"type": "whatif", "content": signal_content}

    # --- Run the real pipeline for a grounded baseline ----------------------
    try:
        state = await _run_pipeline(domain, account_id, signal)
    except Exception:  # noqa: BLE001 - never fail the what-if; degrade offline
        logger.exception("what-if pipeline failed for %s", account_id)
        state = {}

    baseline_rec: Dict[str, Any] = dict(state.get("recommendation") or {})
    candidates: List[Dict[str, Any]] = list(state.get("candidate_actions") or [])
    baseline_risk = float((state.get("risks") or {}).get("score", 0.6))
    baseline_conf = float((baseline_rec.get("confidence") or {}).get("score", 0.7))
    ro_type = (baseline_rec.get("risk_opportunity") or {}).get("type", "risk")

    # --- Apply the counterfactual layer -------------------------------------
    p = _pressures(applied)
    new_risk = _clamp(round(baseline_risk + 0.30 * p["mean_pressure"], 3), 0.05, 0.95)

    rescored = _rescore_candidates(candidates, new_risk)
    new_action: Dict[str, Any]
    if rescored:
        chosen = rescored[0]
        new_action = {
            "key": chosen.get("key", ""),
            "title": chosen.get("title", ""),
            "description": chosen.get("description", ""),
        }
    else:
        new_action = dict(
            baseline_rec.get("action")
            or {
                "key": "schedule_executive_business_review",
                "title": "Schedule an executive business review",
                "description": "Realign with the buying committee before renewal.",
            }
        )

    # Confidence: stronger and more coherent pressure toward the recommended
    # play raises confidence; conflicting inputs add uncertainty.
    direction = 1.0 if ro_type == "risk" else -1.0
    alignment = direction * p["mean_pressure"]
    new_conf = _clamp(round(baseline_conf + 0.22 * alignment - 0.16 * p["conflict"], 3), 0.05, 0.97)

    action_changed = new_action.get("key") != (baseline_rec.get("action") or {}).get("key")

    # --- Assemble the resulting recommendation object -----------------------
    rec = copy.deepcopy(baseline_rec) if baseline_rec else {}
    rec["id"] = f"whatif_{uuid.uuid4().hex[:12]}"
    rec["account_id"] = account_id
    rec["domain"] = domain
    rec["action"] = new_action
    rec["status"] = "proposed"
    rec["confidence"] = {
        "score": new_conf,
        "method": "counterfactual_whatif",
        "label": _label_for(new_conf),
    }
    rec.setdefault("evidence", [])
    rec.setdefault("signals", {"supporting": [], "contradicting": []})
    rec.setdefault(
        "expected_impact",
        {"kpi": "NRR", "direction": "up", "estimate": "+4 to +6 points over 90 days"},
    )
    rec.setdefault("risk_opportunity", {"type": ro_type, "summary": ""})
    rec.setdefault("rationale", "")

    risk_phrase = (
        "elevated" if new_risk > baseline_risk + 0.02
        else "reduced" if new_risk < baseline_risk - 0.02
        else "roughly unchanged"
    )
    rec["counterfactual"] = (
        f"With usage trend {applied['usage_trend']:+.0f}% QoQ, NPS "
        f"{applied['nps']:.0f}/10, and ARR ${applied['arr']:,.0f}, churn risk is "
        f"{risk_phrase} ({baseline_risk:.2f} -> {new_risk:.2f}). "
        + (
            f"The engine now favors '{new_action.get('title', 'a different play')}'."
            if action_changed
            else "The recommended play holds, with recalibrated confidence."
        )
    )

    return {
        "recommendation": rec,
        "baseline": {
            "action": baseline_rec.get("action")
            or {"key": "", "title": "Baseline recommendation", "description": ""},
            "confidence": round(baseline_conf, 3),
            "risk_score": round(baseline_risk, 3),
        },
        "confidence_delta": round(new_conf - baseline_conf, 3),
        "risk_score": {"baseline": round(baseline_risk, 3), "whatif": new_risk},
        "pressures": p,
        "applied_overrides": applied,
        "action_changed": action_changed,
    }
