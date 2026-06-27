"""Play recommender.

Ranks eligible actions from the domain pack for the current decision point, then
reweights them with learned preferences and prior similar episodes from memory.
This is where the learning effect shows up: when a human has previously accepted
or rejected a play on similar accounts, memory preferences shift the ranking.

Produces ``candidate_actions`` ranked by expected value, each annotated with why
it was chosen or why it was passed over (the "why not these" trail). The top
candidates are also distilled into a compact ``alternatives`` list (chosen play
plus up to two runner-ups), each carrying a score, a short rationale, and a
``why_not`` string for the runner-ups so the UI can surface the trade-offs.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents import make_step, safe_get_memory
from app.packs.loader import load_pack
from app.packs.schema import Action, DomainPack
from app.packs.registry import register_agent

# Eligibility and action economics (base value, effort) are now PACK
# CONFIGURATION: ``actions[*].eligible_points``, ``actions[*].base_value`` and
# ``actions[*].effort`` in the domain YAML. The maps below are retained only as a
# SAFE FALLBACK for packs (or actions) that do not declare them, so nothing
# breaks when a pack omits the economics.
#
# Which actions are eligible per decision point, used only when no pack action
# declares ``eligible_points`` for the point. Unknown points fall back to all
# actions.
_ELIGIBLE_BY_POINT: Dict[str, List[str]] = {
    "onboarding_stall": ["assign_onboarding_taskforce", "launch_adoption_campaign", "monitor_no_action"],
    "low_adoption": ["launch_adoption_campaign", "schedule_executive_business_review", "monitor_no_action"],
    "health_drop": ["schedule_executive_business_review", "launch_adoption_campaign", "open_executive_escalation"],
    "renewal_risk": [
        "schedule_executive_business_review",
        "initiate_renewal_motion",
        "offer_save_concession",
        "identify_new_champion",
    ],
    "expansion_signal": ["propose_expansion_offer", "initiate_renewal_motion"],
    "escalation": ["open_executive_escalation", "identify_new_champion", "resolve_billing_dispute"],
    # SaaS sales pack.
    "deal_stall": ["re_engage_buyer"],
    "closing_signal": ["send_proposal"],
}

# Base expected-value priors per action (0..1). The recommender blends these
# with risk magnitude and learned preferences.
_BASE_VALUE = {
    "schedule_executive_business_review": 0.74,
    "initiate_renewal_motion": 0.68,
    "offer_save_concession": 0.6,
    "launch_adoption_campaign": 0.66,
    "assign_onboarding_taskforce": 0.7,
    "open_executive_escalation": 0.72,
    "identify_new_champion": 0.58,
    "propose_expansion_offer": 0.71,
    "resolve_billing_dispute": 0.64,
    "monitor_no_action": 0.3,
    "re_engage_buyer": 0.67,
    "send_proposal": 0.73,
}

# Relative execution effort per action (0..1). Used for the "effort vs impact"
# note so a reviewer can weigh payoff against the work each play requires.
_EFFORT = {
    "monitor_no_action": 0.1,
    "launch_adoption_campaign": 0.45,
    "initiate_renewal_motion": 0.4,
    "schedule_executive_business_review": 0.55,
    "identify_new_champion": 0.6,
    "assign_onboarding_taskforce": 0.7,
    "open_executive_escalation": 0.75,
    "offer_save_concession": 0.65,
    "propose_expansion_offer": 0.6,
    "resolve_billing_dispute": 0.55,
    "re_engage_buyer": 0.35,
    "send_proposal": 0.5,
    # collections
    "send_payment_reminder": 0.15,
    "send_dunning_notice": 0.3,
    "schedule_collection_call": 0.45,
    "negotiate_payment_plan": 0.6,
    "secure_promise_to_pay": 0.4,
    "open_dispute_case": 0.55,
    "place_credit_hold": 0.6,
    "adjust_credit_terms": 0.65,
    "offer_settlement": 0.75,
    "escalate_to_agency": 0.7,
    "recommend_writeoff": 0.6,
}

# How many ranked candidates to expose as user-facing alternatives.
_MAX_ALTERNATIVES = 3


def _bucket(value: float) -> str:
    """Coarse low/medium/high label for a 0..1 value."""

    if value >= 0.66:
        return "high"
    if value >= 0.4:
        return "medium"
    return "low"


def _effort_impact(action_key: str, score: float, effort: float) -> Dict[str, Any]:
    """Return an effort vs impact read for a candidate: labels plus a note."""

    effort_label = _bucket(effort)
    impact_label = _bucket(score)
    # Payoff ratio: impact earned per unit of effort. Above 1 reads as efficient.
    ratio = round(score / effort, 2) if effort > 0 else None

    if impact_label == "high" and effort_label in ("low", "medium"):
        note = f"{impact_label.title()} impact for {effort_label} effort: an efficient play."
    elif impact_label == "low" and effort_label == "high":
        note = f"{impact_label.title()} impact for {effort_label} effort: hard to justify now."
    elif impact_label == effort_label:
        note = f"{impact_label.title()} impact balanced against {effort_label} effort."
    else:
        note = f"{impact_label.title()} impact for {effort_label} effort."

    return {
        "effort": round(effort, 2),
        "effort_label": effort_label,
        "impact_label": impact_label,
        "payoff_ratio": ratio,
        "effort_impact_note": note,
    }


def _eligible_actions(pack: DomainPack, decision_point: str) -> List[Action]:
    """Resolve eligible actions for a decision point, config first.

    Prefers the pack's declared eligibility (``actions[*].eligible_points``).
    Falls back to the built-in ``_ELIGIBLE_BY_POINT`` map, then to all actions,
    so a pack that does not declare eligibility still produces candidates.
    """

    from_pack = pack.actions_for_point(decision_point)
    if from_pack:
        return from_pack

    keys = _ELIGIBLE_BY_POINT.get(decision_point)
    if not keys:
        return list(pack.actions)
    out: List[Action] = []
    for key in keys:
        action = pack.action_by_key(key)
        if action is not None:
            out.append(action)
    return out or list(pack.actions)


def _base_value_for(action: Action) -> float:
    """Expected-value prior for an action: pack value first, then code default."""

    if action.base_value is not None:
        return float(action.base_value)
    return _BASE_VALUE.get(action.key, 0.5)


def _effort_for(action: Action) -> float:
    """Execution effort for an action: pack effort first, then code default."""

    if action.effort is not None:
        return float(action.effort)
    return _EFFORT.get(action.key, 0.5)


def _preference_boost(preferences: Dict[str, Any], action_key: str) -> float:
    """Translate learned preferences into an additive ranking boost."""

    if not preferences:
        return 0.0

    # Common shapes the memory slice might return. Learned action weights are
    # normalized to roughly [-1, 1]; scale them so they meaningfully reorder
    # candidates without saturating the score band.
    weights = preferences.get("action_weights") or preferences.get("weights") or {}
    if isinstance(weights, dict) and action_key in weights:
        try:
            return max(-0.2, min(0.2, float(weights[action_key]) * 0.18))
        except (TypeError, ValueError):
            pass

    preferred = preferences.get("preferred_actions") or preferences.get("accepted") or []
    avoided = preferences.get("avoid_actions") or preferences.get("rejected") or []
    boost = 0.0
    if action_key in preferred:
        boost += 0.12
    if action_key in avoided:
        boost -= 0.18
    return boost


def _episode_boost(episodes: List[Dict[str, Any]], action_key: str) -> float:
    """Boost actions that were accepted on prior similar accounts."""

    boost = 0.0
    for ep in episodes or []:
        ep_action = ep.get("action_key") or (ep.get("recommendation") or {}).get("action", {}).get("key")
        decision = (ep.get("outcome") or {}).get("decision") or ep.get("decision")
        if ep_action != action_key:
            continue
        if decision in ("approve", "approved", "accept", "accepted"):
            boost += 0.08
        elif decision in ("reject", "rejected", "dismiss"):
            boost -= 0.1
    return boost


def _with_note(text: str, candidate: Dict[str, Any]) -> str:
    """Append the candidate's effort-vs-impact note to a reason string."""

    note = candidate.get("effort_impact_note")
    return f"{text} {note}" if note else text


def _runner_up_why_not(chosen: Dict[str, Any], alt: Dict[str, Any]) -> str:
    """Explain, in one line, why this eligible play lost to the chosen one."""

    delta = round(chosen["score"] - alt["score"], 3)
    if alt.get("preference_boost", 0.0) < 0:
        return "Down-weighted by prior human rejections on similar accounts."
    if alt.get("episode_boost", 0.0) < 0:
        return "Similar past plays on this account were not accepted by the team."
    if alt["key"] == "monitor_no_action":
        return "Too passive for the current risk magnitude."
    if delta <= 0:
        return "Effectively tied on value but less decisive than the chosen play."
    return (
        f"Lower expected value (-{delta}) than the chosen play given current risk "
        "and learned preferences."
    )


def _candidate_rationale(candidate: Dict[str, Any]) -> str:
    """Short positive rationale for why a candidate was even in contention."""

    bits: List[str] = [f"Expected value {candidate['score']}"]
    if candidate.get("preference_boost", 0.0) > 0:
        bits.append("favored by learned preferences")
    if candidate.get("episode_boost", 0.0) > 0:
        bits.append("accepted on similar accounts before")
    if candidate.get("risk_term", 0.0) > 0 and candidate["key"] != "monitor_no_action":
        bits.append("scales with the current risk magnitude")
    rationale = "; ".join(bits) + "."
    note = candidate.get("effort_impact_note")
    if note:
        rationale = f"{rationale} {note}"
    return rationale


def build_alternatives(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Distill ranked candidates into user-facing alternatives.

    Returns up to ``_MAX_ALTERNATIVES`` entries shaped as
    ``{action: {key, title, description}, score, rationale, why_not}``. The
    chosen play sits first with ``why_not = None``; runner-ups carry a concise
    reason they were passed over.
    """

    if not candidates:
        return []

    chosen = candidates[0]
    alternatives: List[Dict[str, Any]] = []
    for idx, candidate in enumerate(candidates[:_MAX_ALTERNATIVES]):
        is_chosen = idx == 0
        alternatives.append(
            {
                "action": {
                    "key": candidate["key"],
                    "title": candidate["title"],
                    "description": candidate["description"],
                },
                "score": candidate["score"],
                "rationale": (
                    "Highest expected value given risk magnitude and learned preferences."
                    + (
                        f" {candidate['effort_impact_note']}"
                        if candidate.get("effort_impact_note")
                        else ""
                    )
                    if is_chosen
                    else _candidate_rationale(candidate)
                ),
                "why_not": None if is_chosen else _runner_up_why_not(chosen, candidate),
                "effort_impact": {
                    "effort_label": candidate.get("effort_label"),
                    "impact_label": candidate.get("impact_label"),
                    "note": candidate.get("effort_impact_note"),
                },
                "chosen": is_chosen,
            }
        )
    return alternatives


@register_agent(
    capability="play_recommender",
    description="Ranks eligible plays using pack eligibility plus learned memory.",
    output_keys=["candidate_actions", "alternatives", "preferences", "similar_episodes"],
    cost_tier="strong",
    tags=["decision"],
)
async def node(state: Dict[str, Any]) -> Dict[str, Any]:
    domain = state.get("domain", "customer_success")
    account_id = state.get("account_id", "unknown-account")
    decision_point = state.get("decision_point", "renewal_risk")
    risk_score = float((state.get("risks") or {}).get("score", 0.6))

    pack = load_pack(domain)
    eligible = _eligible_actions(pack, decision_point)

    # A/B memory toggle: when disabled, the recommender uses raw priors only and
    # skips all learned-preference re-ranking (and the memory round-trip).
    disable_memory = bool(state.get("disable_memory"))

    # Pull learned signals from memory (graceful if the slice is absent).
    preferences: Dict[str, Any] = {}
    episodes: List[Dict[str, Any]] = []
    situation = f"{decision_point}: {(state.get('signal') or {}).get('content', '')}".strip()
    memory = None if disable_memory else await safe_get_memory()
    if memory is not None:
        try:
            preferences = await memory.get_preferences(domain) or {}
        except Exception:  # noqa: BLE001
            preferences = {}
        try:
            episodes = (
                await memory.recall_similar(
                    account_id, situation, k=3, org_id=state.get("org_id")
                )
                or []
            )
        except Exception:  # noqa: BLE001
            episodes = []

    candidates: List[Dict[str, Any]] = []
    for action in eligible:
        base = _base_value_for(action)
        effort = _effort_for(action)
        # Higher risk increases the value of decisive plays, lowers monitoring.
        risk_term = (risk_score - 0.5) * (0.4 if action.key != "monitor_no_action" else -0.4)
        # With memory disabled both boosts are zero, so the ranking is raw priors.
        pref = 0.0 if disable_memory else _preference_boost(preferences, action.key)
        epi = 0.0 if disable_memory else _episode_boost(episodes, action.key)
        score = max(0.02, min(0.99, round(base + risk_term + pref + epi, 3)))
        candidate = {
            "key": action.key,
            "title": action.title,
            "description": action.description,
            "eligibility": action.eligibility,
            "score": score,
            "base_value": base,
            "risk_term": round(risk_term, 3),
            "preference_boost": round(pref, 3),
            "episode_boost": round(epi, 3),
        }
        candidate.update(_effort_impact(action.key, score, effort))
        candidates.append(candidate)

    # Primary sort by expected value. Ties are broken by learned memory (a play
    # the team has favored or accepted before wins), then by raw base value, so
    # the learning loop also shows up when two plays are otherwise even.
    candidates.sort(
        key=lambda c: (
            c["score"],
            round(c["preference_boost"] + c["episode_boost"], 3),
            c["base_value"],
        ),
        reverse=True,
    )

    # Annotate the runner-ups with a short "why not" reason on the full list.
    if candidates:
        chosen = candidates[0]
        chosen["chosen"] = True
        chosen["reason"] = _with_note(
            "Highest expected value given risk magnitude and learned preferences.", chosen
        )
        for alt in candidates[1:]:
            alt["chosen"] = False
            alt["reason"] = _with_note(_runner_up_why_not(chosen, alt), alt)

    # Compact, ranked alternatives for the recommendation object and UI.
    alternatives = build_alternatives(candidates)

    learned = bool(preferences) or bool(episodes)

    return {
        "candidate_actions": candidates,
        "alternatives": alternatives,
        "preferences": preferences,
        "similar_episodes": episodes,
        "messages": [
            {
                "role": "play_recommender",
                "content": (
                    f"Ranked {len(candidates)} eligible plays"
                    + (
                        " using raw priors (memory disabled)."
                        if disable_memory
                        else (" using learned memory." if learned else ".")
                    )
                    + (
                        f" Considered {len(alternatives)} top alternatives."
                        if alternatives
                        else ""
                    )
                ),
            }
        ],
        "steps": [
            make_step(
                "play_recommender",
                f"Ranked {len(candidates)} plays; chose "
                + (candidates[0]["key"] if candidates else "none"),
                {
                    "candidates": [
                        {
                            "key": c["key"],
                            "score": c["score"],
                            "chosen": c.get("chosen", False),
                            "effort_label": c.get("effort_label"),
                            "impact_label": c.get("impact_label"),
                            "effort_impact_note": c.get("effort_impact_note"),
                        }
                        for c in candidates
                    ],
                    "alternatives": [
                        {"key": a["action"]["key"], "score": a["score"], "chosen": a["chosen"]}
                        for a in alternatives
                    ],
                    "used_memory": learned,
                    "memory_disabled": disable_memory,
                    "similar_episodes": len(episodes),
                },
            )
        ],
    }
