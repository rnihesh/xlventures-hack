"""Play recommender.

Ranks eligible actions from the domain pack for the current decision point, then
reweights them with learned preferences and prior similar episodes from memory.
This is where the learning effect shows up: when a human has previously accepted
or rejected a play on similar accounts, memory preferences shift the ranking.

Produces ``candidate_actions`` ranked by expected value, each annotated with why
it was chosen or why it was passed over (the "why not these" trail).
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents import make_step, safe_get_memory
from app.packs.loader import load_pack
from app.packs.schema import Action, DomainPack
from app.packs.registry import register_agent

# Which actions are eligible per decision point. Kept as a small mapping so the
# pack stays declarative; unknown decision points fall back to all actions.
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


def _eligible_actions(pack: DomainPack, decision_point: str) -> List[Action]:
    keys = _ELIGIBLE_BY_POINT.get(decision_point)
    if not keys:
        return list(pack.actions)
    out: List[Action] = []
    for key in keys:
        action = pack.action_by_key(key)
        if action is not None:
            out.append(action)
    return out or list(pack.actions)


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


@register_agent(
    capability="play_recommender",
    description="Ranks eligible plays using pack eligibility plus learned memory.",
    output_keys=["candidate_actions", "preferences", "similar_episodes"],
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

    # Pull learned signals from memory (graceful if the slice is absent).
    preferences: Dict[str, Any] = {}
    episodes: List[Dict[str, Any]] = []
    memory = await safe_get_memory()
    situation = f"{decision_point}: {(state.get('signal') or {}).get('content', '')}".strip()
    if memory is not None:
        try:
            preferences = await memory.get_preferences(domain) or {}
        except Exception:  # noqa: BLE001
            preferences = {}
        try:
            episodes = await memory.recall_similar(account_id, situation, k=3) or []
        except Exception:  # noqa: BLE001
            episodes = []

    candidates: List[Dict[str, Any]] = []
    for action in eligible:
        base = _BASE_VALUE.get(action.key, 0.5)
        # Higher risk increases the value of decisive plays, lowers monitoring.
        risk_term = (risk_score - 0.5) * (0.4 if action.key != "monitor_no_action" else -0.4)
        pref = _preference_boost(preferences, action.key)
        epi = _episode_boost(episodes, action.key)
        score = max(0.02, min(0.99, round(base + risk_term + pref + epi, 3)))
        candidates.append(
            {
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
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)

    # Annotate the runner-ups with a short "why not" reason.
    if candidates:
        chosen = candidates[0]
        chosen["chosen"] = True
        chosen["reason"] = "Highest expected value given risk magnitude and learned preferences."
        for alt in candidates[1:]:
            alt["chosen"] = False
            delta = round(chosen["score"] - alt["score"], 3)
            if alt["preference_boost"] < 0:
                alt["reason"] = "Down-weighted by prior human rejections on similar accounts."
            elif alt["key"] == "monitor_no_action":
                alt["reason"] = "Too passive for the current risk magnitude."
            else:
                alt["reason"] = f"Lower expected value (-{delta}) than the chosen play."

    learned = bool(preferences) or bool(episodes)

    return {
        "candidate_actions": candidates,
        "preferences": preferences,
        "similar_episodes": episodes,
        "messages": [
            {
                "role": "play_recommender",
                "content": (
                    f"Ranked {len(candidates)} eligible plays"
                    + (" using learned memory." if learned else ".")
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
                        {"key": c["key"], "score": c["score"], "chosen": c.get("chosen", False)}
                        for c in candidates
                    ],
                    "used_memory": learned,
                    "similar_episodes": len(episodes),
                },
            )
        ],
    }
