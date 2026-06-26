"""LangGraph planner graph.

A real, end to end multi node flow driven by the domain pack and the agent
registry:

    planner -> retrieval -> risk_scorer -> play_recommender ->
    outcome_simulator -> drafter -> critic -> policy_gate -> hitl_gate ->
    commit -> END

The planner reads the domain pack's ``planner_prompt`` and ``decision_points``
to classify the signal and select which specialists to run. Specialist nodes are
resolved from the registry by capability, so the graph topology is stable while
the selected roster is dynamic. The commit node writes an episode to memory so
the learning loop can later record an outcome against it.
"""

from __future__ import annotations

import asyncio

from typing import Any, Dict, List, Tuple

from langgraph.graph import END, START, StateGraph

# Importing the agents package registers every specialist into AGENTS.
import app.agents  # noqa: F401
from app.agents import make_step, safe_get_memory
from app.deps import get_llm
from app.packs.loader import load_pack
from app.packs.registry import AGENTS
from app.graph.state import RunState
from app.policy.engine import evaluate as evaluate_policy
from app.policy.engine import evaluation_summary
from app.policy.rules import load_policies

# The ordered specialist pipeline. Critic always runs; the others are gated by
# the planner's capability selection.
_PIPELINE = [
    "retrieval",
    "risk_scorer",
    "play_recommender",
    "outcome_simulator",
    "drafter",
]


def _safe_llm_text(prompt: str, fallback: str) -> str:
    """Invoke the LLM for a short string, falling back on any error."""

    try:
        llm = get_llm()
    except Exception:  # noqa: BLE001
        return fallback
    if llm is None:
        return fallback
    try:
        result = llm.invoke(prompt)
        text = getattr(result, "content", result)
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:  # noqa: BLE001
        return fallback
    return fallback


def _classify_decision_point(pack: Any, signal: Dict[str, Any]) -> str:
    """Map the incoming signal to a decision point from the pack."""

    signal_type = (signal.get("type") or "").strip()
    if signal_type:
        dp = pack.decision_point_for_signal(signal_type)
        if dp:
            return dp

    # Fall back to a content keyword match against decision point labels.
    content = (signal.get("content") or "").lower()
    for dp_key, dp in pack.decision_points.items():
        if dp.label and dp.label.lower() in content:
            return dp_key
        for trigger in dp.trigger_signals:
            if trigger.replace("_", " ") in content:
                return dp_key

    # Default to a renewal/risk style point if present, else the first one.
    for preferred in ("renewal_risk", "health_drop", "deal_stall"):
        if preferred in pack.decision_points:
            return preferred
    return next(iter(pack.decision_points), "general_review")


# Per decision-point routing profiles. Each entry names the specialist roster
# for that situation plus a one-line rationale. The roster is intersected with
# the registered pipeline at run time, so a profile can reference a specialist
# that is not installed without breaking the graph. Decision points absent here
# fall back to the full standard flow.
_FULL = ["retrieval", "risk_scorer", "play_recommender", "outcome_simulator", "drafter"]

_ROUTING: Dict[str, Dict[str, Any]] = {
    # Opportunities: size the upside (simulate) and prepare outreach to capture it.
    "expansion_signal": {
        "caps": _FULL,
        "rationale": "Expansion opportunity: rank plays, simulate the upside, and draft outreach to act on it.",
    },
    "closing_signal": {
        "caps": _FULL,
        "rationale": "Closing opportunity: rank plays, project velocity, and draft the proposal outreach.",
    },
    # Escalations are urgent: prioritize a drafted response over KPI simulation.
    "escalation": {
        "caps": ["retrieval", "risk_scorer", "play_recommender", "drafter"],
        "rationale": "Escalation: move fast to a grounded, drafted response and skip slower KPI simulation.",
    },
    "high_value_recovery": {
        "caps": ["retrieval", "risk_scorer", "play_recommender", "drafter"],
        "rationale": "High-value recovery: prioritize a relationship-aware, drafted outreach over simulation.",
    },
    "pre_writeoff": {
        "caps": ["retrieval", "risk_scorer", "play_recommender"],
        "rationale": "Pre-write-off: focus on evidence and the recovery decision; no outreach drafted here.",
    },
    # Credit / dispute reviews are internal analysis, not customer outreach.
    "credit_risk_review": {
        "caps": ["retrieval", "risk_scorer", "play_recommender", "outcome_simulator"],
        "rationale": "Credit review: quantify exposure and the treatment decision; outreach is not drafted.",
    },
    "dispute_resolution": {
        "caps": ["retrieval", "risk_scorer", "play_recommender"],
        "rationale": "Dispute: ground the case and decide routing before any dunning outreach.",
    },
    # Pure monitoring: analyze and rank, but produce no outreach artifact.
    "general_review": {
        "caps": ["retrieval", "risk_scorer", "play_recommender"],
        "rationale": "General review: retrieve, score, and rank options without drafting outreach.",
    },
}

_DEFAULT_RATIONALE = (
    "Standard decision flow: retrieve evidence, score risk, rank plays, "
    "simulate impact, and draft outreach."
)


def _select_plan(decision_point: str) -> Tuple[List[str], str]:
    """Choose the specialist roster and rationale for a decision point.

    Routing is genuinely dynamic: expansion and escalation, for example, pull
    different specialists. The chosen roster is intersected with the registered
    pipeline so the graph topology stays stable while the active set varies.
    """

    profile = _ROUTING.get(decision_point)
    template = profile["caps"] if profile else _FULL
    rationale = profile["rationale"] if profile else _DEFAULT_RATIONALE
    caps = [c for c in template if c in _PIPELINE and AGENTS.has(c)]
    if not caps:
        # Never leave the run with no specialists: fall back to whatever is registered.
        caps = [c for c in _PIPELINE if AGENTS.has(c)]
    return caps, rationale


async def planner_node(state: RunState) -> Dict[str, Any]:
    """Classify the signal, select specialists, and draft the plan."""

    domain = state.get("domain", "customer_success")
    signal = dict(state.get("signal") or {})
    pack = load_pack(domain)

    decision_point = _classify_decision_point(pack, signal)
    capabilities, plan_rationale = _select_plan(decision_point)

    dp = pack.decision_points.get(decision_point)
    dp_label = dp.label if dp else decision_point

    prompt = (
        f"{pack.planner_prompt}\n\n"
        f"Account signal: {signal.get('content', '')}. "
        f"Classified decision point: {dp_label}. "
        "List the ordered specialist steps to run as a newline separated list."
    )
    fallback = "\n".join(
        f"Run {cap.replace('_', ' ')}" for cap in capabilities + ["critic"]
    )
    raw = await asyncio.to_thread(_safe_llm_text, prompt, fallback)
    plan = [line.strip(" -*0123456789.") for line in raw.splitlines() if line.strip()]
    if not plan:
        plan = [s.strip() for s in fallback.splitlines()]

    roster = ", ".join(capabilities) or "critic only"
    return {
        "decision_point": decision_point,
        "domain_pack_key": domain,
        "capabilities": capabilities,
        "plan": plan,
        "messages": [
            {
                "role": "planner",
                "content": (
                    f"Classified as {dp_label}; routed {len(capabilities)} specialists "
                    f"({roster}). {plan_rationale}"
                ),
            }
        ],
        "steps": [
            make_step(
                "planner",
                f"Classified decision point: {dp_label}; routed {len(capabilities)} specialists",
                {
                    "decision_point": decision_point,
                    "capabilities": capabilities + ["critic"],
                    "plan": plan,
                    "plan_rationale": plan_rationale,
                    "routing": {"roster": capabilities, "rationale": plan_rationale},
                },
            )
        ],
    }


def _make_specialist_node(capability: str):
    """Wrap a registered specialist so it is skipped when not selected."""

    async def _node(state: RunState) -> Dict[str, Any]:
        caps = state.get("capabilities") or []
        if capability not in caps:
            return {
                "steps": [
                    make_step(capability, f"Skipped {capability}", {"skipped": True})
                ]
            }
        card = AGENTS.get(capability)
        return await card.node(dict(state))

    _node.__name__ = f"{capability}_node"
    return _node


async def critic_node(state: RunState) -> Dict[str, Any]:
    """Run the critic specialist (always on)."""

    card = AGENTS.get("critic")
    return await card.node(dict(state))


def _account_context(state: RunState) -> Dict[str, Any]:
    """Assemble a best-effort account dict for policy evaluation.

    Prefers the accounts seed (so account-scoped rules have data) and always
    falls back to the minimal identity from state, so evaluation works offline
    and never raises.
    """

    account_id = state.get("account_id", "")
    domain = state.get("domain", "customer_success")
    base: Dict[str, Any] = {"account_id": account_id, "domain": domain}
    try:
        from app.api.accounts import _BY_ID  # type: ignore

        account = _BY_ID.get(account_id)
        if account:
            return {**account, "domain": account.get("domain", domain)}
    except Exception:  # noqa: BLE001 - accounts slice is optional
        pass
    return base


async def policy_gate_node(state: RunState) -> Dict[str, Any]:
    """Evaluate the recommendation against the domain's declarative policies.

    Runs the pure, offline policy engine, attaches the gate results to the
    recommendation under ``recommendation['policy']`` (and to the trace), and
    forces human review when any failing gate requires approval. Existing critic
    fields are preserved; only ``requires_hitl`` is escalated, never relaxed.
    """

    domain = state.get("domain", "customer_success")
    recommendation = dict(state.get("recommendation") or {})

    rules = load_policies(domain)
    account = _account_context(state)
    results = evaluate_policy(recommendation, account, rules)
    summary = evaluation_summary(results)

    # Make the guardrail layer visible on the recommendation itself.
    recommendation["policy"] = results

    # Escalate to human review when a failing gate demands approval. Never
    # downgrade an existing critic requirement.
    critic = dict(state.get("critic") or {})
    forced = bool(summary.get("requires_approval"))
    critic["requires_hitl"] = bool(critic.get("requires_hitl")) or forced
    critic["policy_summary"] = summary

    if forced:
        gist = "Policy gate requires approval"
    elif summary.get("warned"):
        gist = "Policy gate passed with warnings"
    else:
        gist = "Policy gate cleared"
    detail = (
        f"{gist}: {summary['passed']} pass, {summary['warned']} warn, "
        f"{summary['failed']} fail of {summary['total']}."
    )

    return {
        "recommendation": recommendation,
        "critic": critic,
        "messages": [{"role": "policy_gate", "content": detail}],
        "steps": [
            make_step(
                "policy_gate",
                detail,
                {"results": results, "summary": summary},
            )
        ],
    }


async def hitl_gate_node(state: RunState) -> Dict[str, Any]:
    """Record whether the recommendation routes to a human.

    The actual interrupt is surfaced to the UI as a ``hitl.required`` event by
    the runs API based on the critic verdict; this node records the routing in
    the trace so the decision is auditable.
    """

    critic = state.get("critic") or {}
    requires_hitl = bool(critic.get("requires_hitl"))
    summary = "Routed to human approval" if requires_hitl else "Auto-approved (reversible, high confidence)"
    return {
        "messages": [{"role": "hitl_gate", "content": summary}],
        "steps": [
            make_step("hitl_gate", summary, {"requires_hitl": requires_hitl})
        ],
    }


async def commit_node(state: RunState) -> Dict[str, Any]:
    """Write an episode to memory so an outcome can be recorded later."""

    recommendation = state.get("recommendation") or {}
    account_id = state.get("account_id", "unknown-account")
    domain = state.get("domain", "customer_success")
    decision_point = state.get("decision_point", "")
    signal = state.get("signal") or {}
    situation = f"{decision_point}: {signal.get('content', '')}".strip()
    action_key = (recommendation.get("action") or {}).get("key", "")

    episode_id = None
    memory = await safe_get_memory()
    if memory is not None and recommendation:
        try:
            episode_id = await memory.write_episode(
                account_id=account_id,
                domain=domain,
                situation=situation,
                action_key=action_key,
                recommendation=recommendation,
            )
        except Exception:  # noqa: BLE001 - never fail the run on a memory write
            episode_id = None

    return {
        "episode_id": episode_id,
        "steps": [
            make_step(
                "commit",
                "Wrote decision episode to memory"
                if episode_id
                else "Decision recorded (memory unavailable)",
                {"episode_id": episode_id, "action_key": action_key},
            )
        ],
    }


def build_graph(checkpointer: Any):
    """Build and compile the planner StateGraph with the given checkpointer."""

    graph = StateGraph(RunState)

    graph.add_node("planner", planner_node)
    for capability in _PIPELINE:
        graph.add_node(capability, _make_specialist_node(capability))
    graph.add_node("critic", critic_node)
    graph.add_node("policy_gate", policy_gate_node)
    graph.add_node("hitl_gate", hitl_gate_node)
    graph.add_node("commit", commit_node)

    graph.add_edge(START, "planner")
    ordered = ["planner", *_PIPELINE, "critic", "policy_gate", "hitl_gate", "commit"]
    for src, dst in zip(ordered, ordered[1:]):
        graph.add_edge(src, dst)
    graph.add_edge("commit", END)

    return graph.compile(checkpointer=checkpointer)
