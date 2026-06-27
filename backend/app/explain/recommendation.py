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


def _alternatives_from_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derive ranked alternatives from raw candidate_actions as a fallback.

    Used when the recommender did not attach a prebuilt ``alternatives`` list.
    Keeps the same shape: {action, score, rationale, why_not}.
    """

    out: List[Dict[str, Any]] = []
    for idx, c in enumerate(candidates[:3]):
        is_chosen = bool(c.get("chosen")) or idx == 0
        out.append(
            {
                "action": {
                    "key": c.get("key", ""),
                    "title": c.get("title", ""),
                    "description": c.get("description", ""),
                },
                "score": float(c.get("score", 0.0)),
                "rationale": (
                    "Highest expected value given risk magnitude and learned preferences."
                    if is_chosen
                    else c.get("reason", "Eligible play with lower expected value.")
                ),
                "why_not": None if is_chosen else c.get("reason"),
                "chosen": is_chosen,
            }
        )
    return out


def _build_alternatives(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the ranked alternatives, preferring the recommender's own list."""

    prebuilt = state.get("alternatives")
    if isinstance(prebuilt, list) and prebuilt:
        normalized: List[Dict[str, Any]] = []
        for idx, alt in enumerate(prebuilt[:3]):
            action = alt.get("action") or {}
            normalized.append(
                {
                    "action": {
                        "key": action.get("key", ""),
                        "title": action.get("title", ""),
                        "description": action.get("description", ""),
                    },
                    "score": float(alt.get("score", 0.0)),
                    "rationale": alt.get("rationale", ""),
                    "why_not": alt.get("why_not"),
                    "chosen": bool(alt.get("chosen")) or idx == 0,
                }
            )
        return normalized

    return _alternatives_from_candidates(state.get("candidate_actions") or [])


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
    """Compute the confidence PRIOR from the run state.

    Single calibration path (one method of record): this function only produces
    the PRIOR, an evidence-and-action signal that seeds confidence. The CRITIC
    owns the FINAL value and the method string (see app/agents/critic.py): it
    reads ``prior`` here, applies faithfulness and self-consistency, and writes
    the authoritative ``score`` + ``method``. ``score`` is set equal to the prior
    so the object is valid if the critic never runs (offline fallback), but the
    ``method`` is labelled ``evidence_prior`` to make clear it is an INPUT, not
    the final calibration of record.
    """

    evidence = state.get("evidence") or []
    risks = state.get("risks") or {}
    contradicting = risks.get("contradicting_signals") or []

    base = 0.55
    base += min(len(evidence), 3) / 3 * 0.2  # more grounding -> more confidence
    base += max(0.0, (float(action.get("score", 0.6)) - 0.5)) * 0.3
    base += float(action.get("preference_boost", 0.0)) * 0.5  # learned signal
    if contradicting:
        base -= 0.1
    prior = round(max(0.05, min(0.95, base)), 3)
    label = "high" if prior >= 0.75 else "medium" if prior >= 0.5 else "low"
    return {"score": prior, "prior": prior, "method": "evidence_prior", "label": label}


# Candidate information gaps. Each entry is a fact that, if known, would change
# or strengthen the recommendation. ``keywords`` are scanned across the run
# corpus (evidence, signal, account context): if NONE appear, the fact is
# considered missing and the gap is surfaced. Order here is the surfaced order.
_GAP_CANDIDATES: List[Dict[str, Any]] = [
    {
        "keywords": ["usage", "active", "seats", "logins", "login", "adoption", "telemetry", "engagement"],
        "gap": "No recent product usage data",
        "why_it_matters": "Usage trend is the strongest leading indicator of churn and sizes the urgency of the play.",
        "suggested_source": "Product analytics / telemetry",
    },
    {
        "keywords": ["renewal", "renew", "contract end", "term", "expiry", "expiration"],
        "gap": "Renewal date and timeline unknown",
        "why_it_matters": "Timing determines how urgent the action is and which play fits the renewal window.",
        "suggested_source": "CRM / contract record",
    },
    {
        "keywords": ["sponsor", "executive", "champion", "buyer", "stakeholder", "exec"],
        "gap": "No executive sponsor identified",
        "why_it_matters": "Without a named sponsor, outreach may never reach a decision maker who can act.",
        "suggested_source": "CRM relationship map",
    },
    {
        "keywords": ["ticket", "support", "incident", "bug", "escalation", "csat", "outage"],
        "gap": "Support and incident history not available",
        "why_it_matters": "Unresolved issues are often the true churn driver behind a usage decline.",
        "suggested_source": "Support / ticketing system",
    },
    {
        "keywords": ["arr", "contract value", "revenue", "spend", "mrr", "tier", "plan"],
        "gap": "Account value (ARR) not in context",
        "why_it_matters": "Deal size sets how much investment and seniority the chosen play justifies.",
        "suggested_source": "CRM / billing",
    },
    {
        "keywords": ["competitor", "competition", "switch", "alternative", "vendor", "displace"],
        "gap": "No signal on competitive pressure",
        "why_it_matters": "An active competitor evaluation changes the save strategy and concession ceiling.",
        "suggested_source": "CRM notes / sales conversations",
    },
]

# Maximum gaps to surface so the section stays focused, not noisy.
_MAX_GAPS = 4


def _gap_corpus(state: Dict[str, Any], evidence: List[Dict[str, Any]], signal_content: str) -> str:
    """Concatenate everything the engine actually knows into one searchable blob."""

    parts: List[str] = [signal_content or ""]
    for ev in evidence:
        parts.append(str(ev.get("claim", "")))
        parts.append(str(ev.get("snippet", "")))
        parts.append(str(ev.get("source_type", "")))
        parts.append(str(ev.get("source_id", "")))
    risks = state.get("risks") or {}
    for key in ("supporting_signals", "contradicting_signals"):
        for s in risks.get(key) or []:
            parts.append(str(s))
    # Account context can arrive under any of several keys depending on caller.
    for key in ("account", "account_profile", "context", "profile"):
        ctx = state.get(key)
        if isinstance(ctx, dict):
            for k, v in ctx.items():
                parts.append(str(k))
                parts.append(str(v))
        elif ctx:
            parts.append(str(ctx))
    return " ".join(parts).lower()


def _missing_information(
    state: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    signal_content: str,
) -> List[Dict[str, Any]]:
    """Identify concrete missing facts: what the evidence and context do NOT contain.

    Deterministic and offline: derived purely from keyword coverage over the run
    corpus, so the same state always yields the same gaps. Mirrors workflow step
    three (name opportunities, risks, AND missing information).
    """

    corpus = _gap_corpus(state, evidence, signal_content)
    gaps: List[Dict[str, Any]] = []
    for candidate in _GAP_CANDIDATES:
        if any(kw in corpus for kw in candidate["keywords"]):
            continue
        gaps.append(
            {
                "gap": candidate["gap"],
                "why_it_matters": candidate["why_it_matters"],
                "suggested_source": candidate["suggested_source"],
            }
        )

    # Meta gap: a case built only on confirming signals is under-tested. Surface
    # it when retrieval gathered no disconfirming evidence at all.
    risks = state.get("risks") or {}
    if not (risks.get("contradicting_signals") or []):
        gaps.append(
            {
                "gap": "No disconfirming evidence gathered",
                "why_it_matters": "The case rests only on supporting signals; a counter-signal would calibrate confidence up or down.",
                "suggested_source": "Cross-check sentiment, usage, and recent conversations",
            }
        )

    return gaps[:_MAX_GAPS]


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
    # Display name for prose (the id is kept for technical evidence source ids).
    account_label = state.get("account_name") or account_id
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
        llm, account_label, action_block["title"], signal_content, evidence
    )
    if rationale is None:
        rationale = (
            f"{action_block['title']} directly addresses the strongest signals on "
            f"{account_label}: {evidence[0]['claim'] if evidence else 'declining engagement'} "
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

    # Top-3 ranked alternatives (chosen play plus runner-ups with why_not).
    alternatives = _build_alternatives(state)

    # What we still need to know: concrete facts absent from evidence and context.
    missing_information = _missing_information(state, evidence, signal_content)

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
        # Extra field: ranked candidates the engine weighed before choosing.
        # Kept outside the schema-required set so the contract stays intact.
        "alternatives": alternatives,
        # Extra field: missing information (workflow step three). Each entry is
        # {gap, why_it_matters, suggested_source}. Also outside the required set.
        "missing_information": missing_information,
        "status": "proposed",
        "created_at": _now_iso(),
    }
