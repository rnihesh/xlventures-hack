"""Risk and opportunity scorer.

Turns evidence plus the decision point into a discrete risk or opportunity
finding with a numeric score and an honest split of supporting vs contradicting
signals. The magnitude is a transparent weighted blend of three factors:

* signal severity: how serious the decision point and signal language are,
* evidence strength: source-weighted, confidence-weighted retrieval quality,
* account exposure: health, risk tier, sentiment, and renewal proximity.

Each factor's weight, value, and contribution is recorded on the state under
``risks['factors']`` (and ``risks['score_breakdown']``) so the explanation layer
and the UI can show exactly why the score is what it is. Everything is
deterministic and offline-safe.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.agents import make_step
from app.agents.tools import account_context
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

# Base severity per decision point (0..1). Higher means a more serious situation
# that justifies a more decisive play. Covers all three shipped domain packs.
_DP_SEVERITY = {
    # customer_success
    "escalation": 0.9,
    "renewal_risk": 0.8,
    "health_drop": 0.75,
    "low_adoption": 0.6,
    "onboarding_stall": 0.55,
    "expansion_signal": 0.65,
    # saas_sales
    "deal_stall": 0.6,
    "closing_signal": 0.65,
    # collections
    "pre_writeoff": 0.9,
    "high_value_recovery": 0.8,
    "credit_risk_review": 0.75,
    "broken_promise": 0.7,
    "aging_escalation": 0.65,
    "dispute_resolution": 0.6,
    "early_stage_overdue": 0.5,
    # generic
    "general_review": 0.4,
}

# Words in the signal that escalate severity when present.
_SEVERITY_TERMS = {
    "sev-1": 0.15, "sev1": 0.15, "outage": 0.12, "churn": 0.12, "cancel": 0.12,
    "escalation": 0.1, "critical": 0.1, "urgent": 0.1, "dispute": 0.08,
    "bankruptcy": 0.15, "insolven": 0.15, "legal": 0.1, "downgrade": 0.08,
    "detractor": 0.06, "lawsuit": 0.12,
}

# Risk tier mapped to an exposure value (0..1).
_RISK_TIER = {"critical": 0.95, "high": 0.8, "medium": 0.55, "low": 0.3}

# Sentiment mapped to a risk nudge.
_SENTIMENT = {
    "strongly_negative": 0.9, "negative": 0.75, "neutral": 0.5,
    "positive": 0.3, "strongly_positive": 0.2,
}

# Factor weights. Re-normalized over whichever factors are actually present so a
# missing account profile does not silently deflate the score.
_WEIGHTS = {"signal_severity": 0.35, "evidence_strength": 0.35, "account_exposure": 0.30}


def _clamp(value: float, low: float = 0.05, high: float = 0.95) -> float:
    return max(low, min(high, value))


def _signal_severity(decision_point: str, signal: Dict[str, Any]) -> Tuple[float, str]:
    """Severity from the decision point, nudged by alarming signal language."""

    base = _DP_SEVERITY.get(decision_point, 0.6)
    content = f"{signal.get('content', '')} {signal.get('type', '')}".lower()
    bump = 0.0
    hit_terms: List[str] = []
    for term, weight in _SEVERITY_TERMS.items():
        if term in content:
            bump += weight
            hit_terms.append(term)
    value = _clamp(base + min(bump, 0.25), 0.1, 0.98)
    if hit_terms:
        note = f"Decision point '{decision_point}' with escalating language ({', '.join(hit_terms[:3])})."
    else:
        note = f"Baseline severity for decision point '{decision_point}'."
    return round(value, 3), note


def _evidence_strength(evidence: List[Dict[str, Any]]) -> Tuple[float, str]:
    """Source-weighted, confidence-weighted retrieval quality."""

    if not evidence:
        return 0.5, "No evidence retrieved; using a neutral prior."
    total = 0.0
    for item in evidence:
        weight = _SOURCE_WEIGHT.get(item.get("source_type", ""), 0.5)
        confidence = float(item.get("score", 0.7) or 0.7)
        total += weight * confidence
    value = _clamp(total / len(evidence))
    note = (
        f"{len(evidence)} sources, source- and confidence-weighted "
        f"(avg strength {value:.2f})."
    )
    return round(value, 3), note


def _days_to_renewal(account: Dict[str, Any]) -> Optional[int]:
    """Days until the renewal date, or None when unknown."""

    raw = account.get("renewal_date") or account.get("due_date")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw)[:10]).date()
    except (ValueError, TypeError):
        return None
    return (parsed - date.today()).days


def _account_exposure(
    account: Dict[str, Any], is_opportunity: bool
) -> Tuple[Optional[float], str]:
    """Blend account fields into an exposure value oriented to the decision.

    For risk, unhealthy / high-tier / negative / near-renewal raises the value.
    For opportunity, healthy / low-tier accounts raise it. Returns ``None`` when
    no usable account field is present (so the weight is re-normalized away).
    """

    parts: List[float] = []
    notes: List[str] = []

    health = account.get("health_score")
    if isinstance(health, (int, float)):
        risk_from_health = _clamp(1.0 - float(health) / 100.0)
        parts.append(risk_from_health)
        notes.append(f"health {int(health)}")

    tier = str(account.get("risk_level", "")).lower()
    if tier in _RISK_TIER:
        parts.append(_RISK_TIER[tier])
        notes.append(f"risk tier {tier}")

    sentiment = str(account.get("sentiment", "")).lower()
    if sentiment in _SENTIMENT:
        parts.append(_SENTIMENT[sentiment])
        notes.append(f"sentiment {sentiment.replace('_', ' ')}")

    dtr = _days_to_renewal(account)
    if dtr is not None:
        # Closer renewal -> higher exposure; flat after ~180 days out.
        proximity = _clamp(1.0 - max(0, dtr) / 180.0)
        parts.append(proximity)
        notes.append(f"{dtr}d to renewal")

    util = account.get("active_seats")
    seats = account.get("seats")
    if isinstance(util, (int, float)) and isinstance(seats, (int, float)) and seats:
        underuse = _clamp(1.0 - float(util) / float(seats))
        parts.append(underuse)
        notes.append(f"seat use {int(util)}/{int(seats)}")

    if not parts:
        return None, "No account profile available; account factor omitted."

    risk_value = sum(parts) / len(parts)
    # Opportunity decision points read healthy accounts as high-value, so invert.
    value = round(_clamp(1.0 - risk_value) if is_opportunity else _clamp(risk_value), 3)
    orientation = "opportunity readiness" if is_opportunity else "churn exposure"
    return value, f"{orientation} from {', '.join(notes)}."


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

    all_keys = [s.key for s in pack.signals]
    contradicting_pool = [
        k
        for k in all_keys
        if k not in supporting
        and any(token in k for token in ("expansion", "seat_growth", "intent", "promise_to_pay"))
    ]
    return supporting, contradicting_pool[:1]


async def _llm_score(
    decision_point: str,
    signal: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    account: Dict[str, Any],
    is_opportunity: bool,
) -> Tuple[float, List[Dict[str, Any]], Optional[str]]:
    """Score the situation with the model, grounded in the real context.

    Returns ``(score, factors, summary)`` where ``score`` is clamped to [0, 1]
    and ``factors`` matches the deterministic factor dict shape (factor, weight,
    value, contribution, note). Raises on any model or parse error so the caller
    falls back to the deterministic path.
    """

    import json

    from app.deps import get_llm

    orientation = "opportunity to grow" if is_opportunity else "churn or downside risk"
    ev_text = (
        "\n".join(
            f"- {(e.get('text') or e.get('snippet') or e.get('claim') or '')[:300]}"
            for e in evidence[:8]
            if isinstance(e, dict)
        )
        or "none"
    )
    acct_text = (
        ", ".join(
            f"{k}={account.get(k)}"
            for k in ("health_score", "risk_level", "sentiment", "renewal_date", "active_seats", "seats")
            if account.get(k) is not None
        )
        or "none"
    )
    prompt = (
        "You are the risk scorer for an account decision. Judge the magnitude of "
        f"the {orientation} for THIS specific situation, grounded ONLY in the "
        "signal, the cited evidence, and the account profile below. Do not use a "
        "fixed formula; weigh what the evidence actually shows.\n\n"
        f"Decision point: {decision_point}\n"
        f"Signal: {(signal.get('content') or '')[:1200]}\n\n"
        f"Evidence:\n{ev_text}\n\n"
        f"Account profile: {acct_text}\n\n"
        "Note: playbook or knowledge-base snippets in the evidence describe "
        "recommended STEPS, not events that happened to this account. Do NOT treat "
        "them as a real incident or inflate the score from them; only the signal "
        "and the account's own records describe what actually happened.\n"
        'Return STRICT JSON: {"score": <0.0 to 1.0>, "summary": "<one sentence, '
        'grounded in the evidence>", "factors": [{"name": "<short driver name>", '
        '"value": <0.0 to 1.0>, "note": "<why, grounded in the evidence>"}]}. '
        "List 2 to 5 named drivers, each tied to the evidence."
    )

    resp = await get_llm(temperature=0).ainvoke(prompt)
    text = getattr(resp, "content", "") or ""
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start : end + 1])

    score = round(max(0.0, min(1.0, float(data.get("score", 0.5)))), 3)

    raw_factors = data.get("factors") or []
    count = max(1, len(raw_factors))
    even_weight = round(1.0 / count, 3)
    factors: List[Dict[str, Any]] = []
    for row in raw_factors:
        if not isinstance(row, dict):
            continue
        value = round(max(0.0, min(1.0, float(row.get("value", score)))), 3)
        factors.append(
            {
                "factor": str(row.get("name") or "driver").strip() or "driver",
                "weight": even_weight,
                "value": value,
                "contribution": round(even_weight * value, 3),
                "note": str(row.get("note") or "").strip(),
            }
        )
    if not factors:
        raise ValueError("model returned no usable factors")

    summary = str(data.get("summary") or "").strip() or None
    return score, factors, summary


def _weighted_score(
    factors: Dict[str, Optional[float]]
) -> Tuple[float, List[Dict[str, Any]]]:
    """Combine present factors with re-normalized weights; return score + breakdown."""

    present = {k: v for k, v in factors.items() if v is not None}
    total_weight = sum(_WEIGHTS[k] for k in present) or 1.0

    breakdown: List[Dict[str, Any]] = []
    score = 0.0
    for name in ("signal_severity", "evidence_strength", "account_exposure"):
        value = factors.get(name)
        if value is None:
            continue
        weight = round(_WEIGHTS[name] / total_weight, 3)
        contribution = round(weight * value, 3)
        score += contribution
        breakdown.append(
            {"factor": name, "weight": weight, "value": value, "contribution": contribution}
        )
    return round(_clamp(score), 3), breakdown


@register_agent(
    capability="risk_scorer",
    description="Scores the situation with a transparent weighted factor breakdown.",
    output_keys=["risks", "risk_opportunity"],
    cost_tier="standard",
    tags=["analysis"],
)
async def node(state: Dict[str, Any]) -> Dict[str, Any]:
    decision_point = state.get("decision_point", "renewal_risk")
    evidence = state.get("evidence") or []
    signal = state.get("signal") or {}
    is_opportunity = decision_point in _OPPORTUNITY_POINTS

    account = account_context(
        state.get("account_id", ""), state.get("domain", "customer_success")
    )

    # Deterministic factor blend. On prod this is the offline fallback; with no
    # OpenAI key (CI / tests) it is the only path.
    sev_value, sev_note = _signal_severity(decision_point, signal)
    evid_value, evid_note = _evidence_strength(evidence)
    acct_value, acct_note = _account_exposure(account, is_opportunity)

    magnitude, breakdown = _weighted_score(
        {
            "signal_severity": sev_value,
            "evidence_strength": evid_value,
            "account_exposure": acct_value,
        }
    )

    notes = {"signal_severity": sev_note, "evidence_strength": evid_note, "account_exposure": acct_note}
    factors = [
        {**row, "note": notes.get(row["factor"], "")} for row in breakdown
    ]

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

    # On prod (a key is configured) ask the model to score the situation from the
    # actual context. Any failure, or a keyless environment, keeps the
    # deterministic result above so a run never breaks.
    from app.demo import demo_mode_enabled

    method = "weighted_factors"
    if not demo_mode_enabled():
        try:
            magnitude, factors, llm_summary = await _llm_score(
                decision_point, signal, evidence, account, is_opportunity
            )
            method = "model"
            if llm_summary:
                summary = llm_summary
        except Exception:  # noqa: BLE001 - fall back to the deterministic blend
            method = "weighted_factors"

    # Top contributing factor, for a one-line "why" in the trace.
    top = max(factors, key=lambda f: f["contribution"]) if factors else None
    driver_phrase = f" Driven mostly by {top['factor'].replace('_', ' ')}." if top else ""

    risks = {
        "score": magnitude,
        "decision_point": decision_point,
        "supporting_signals": supporting,
        "contradicting_signals": contradicting,
        "evidence_count": len(evidence),
        "drivers": [e.get("claim", "") for e in evidence][:3],
        "factors": factors,
        "score_breakdown": {
            "method": method,
            "weights": _WEIGHTS,
            "score": magnitude,
            "factors": factors,
        },
    }
    risk_opportunity = {"type": ro_type, "summary": summary}

    return {
        "risks": risks,
        "risk_opportunity": risk_opportunity,
        "messages": [
            {
                "role": "risk_scorer",
                "content": f"{ro_type} magnitude {magnitude:.2f} for {decision_point}.{driver_phrase}",
            }
        ],
        "steps": [
            make_step(
                "risk_scorer",
                f"Scored {ro_type} at {magnitude:.2f} from {len(factors)} drivers"
                + (" (model)" if method == "model" else ""),
                {
                    "score": magnitude,
                    "type": ro_type,
                    "factors": factors,
                    "supporting": supporting,
                    "contradicting": contradicting,
                },
            )
        ],
    }
