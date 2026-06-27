"""LangGraph planner graph: a dynamic, supervisor-routed decision engine.

This is not a fixed chain. The planner classifies the decision point from the
incoming signal and the domain pack, then selects WHICH specialists to run (and
in what dependency-valid order). Routing is implemented with conditional edges,
so unselected specialists are never entered (no dead "skipped" steps) and the
engine can loop when it needs more grounding.

Graph shape (conceptual order; selectable nodes are gated by the planner roster,
always-on nodes are marked ``*``)::

                          START
                            v
                        planner*
                            v
        +------------- retrieval <-----------------------+
        |                   v                            |  (replan: re-retrieve)
        |             risk_scorer                        |
        |                   v                            |
        |   gap_analysis* --+--> (clarify loop) --------+   (back to retrieval when
        |                   v        ^                       critical info is absent)
        |          play_recommender  |                       |
        |                   v        +-----------------------+
        |          outcome_simulator         (replan: re-rank)
        |                   v                            ^
        |               drafter                          |
        |                   v                            |
        +-----------> critic* --(replan?)----------------+
                            v
                       policy_gate*
                            v
                        hitl_gate*
                            v
                         commit*
                            v
                           END

Three control loops make the orchestration genuinely agentic:

1. Dynamic specialist selection. ``_select_roster`` picks a roster per decision
   point from the pack's candidate roster (expansion, escalation, and a general
   review pull different sets): LLM-driven online, deterministic offline. The
   roster is recorded as a structured plan + rationale in state, and conditional
   edges walk only the selected nodes.
2. Clarify loop (PDF step 3). ``gap_analysis`` is a first-class node that names
   the concrete missing information. When critical facts are absent it routes
   back to retrieval with gap-targeted sub-queries (bounded by
   ``MAX_CLARIFY_LOOPS``) before the engine commits to a recommendation.
3. Replan loop. When the critic fails faithfulness or confidence is genuinely
   low, the engine routes back to re-retrieve (thin/uncited evidence) or
   re-recommend (adequate evidence, weak pick), bounded by ``MAX_REPLAN_LOOPS``,
   instead of merely lowering the confidence number.

Durable checkpointing: ``build_graph`` compiles against whatever checkpointer is
passed in. ``app.deps.get_checkpointer`` returns an ``AsyncPostgresSaver`` when
``DATABASE_URL`` is set (durable, resumable runs) and an in-memory ``MemorySaver``
otherwise, so the same graph runs offline with no database.

Specialist nodes are resolved from the agent registry by capability, so the
topology is stable while the active roster is dynamic. The commit node writes an
episode to memory so the learning loop can later record an outcome against it.
"""

from __future__ import annotations

import asyncio

from typing import Any, Callable, Dict, List, Optional, Tuple

from langgraph.graph import END, START, StateGraph

# Importing the agents package registers every specialist into AGENTS.
import app.agents  # noqa: F401
from app.agents import make_step, safe_get_memory
from app.agents.gap_analysis import analyze_gaps, gap_targeted_queries
from app.demo import demo_mode_enabled
from app.deps import get_llm
from app.packs.loader import load_pack
from app.packs.registry import AGENTS
from app.graph.state import RunState
from app.policy.engine import evaluate as evaluate_policy
from app.policy.engine import evaluation_summary
from app.policy.rules import load_policies

# The selectable specialist roster the planner draws from. Each is gated by the
# planner's capability selection; the routers skip any not chosen.
_PIPELINE = [
    "retrieval",
    "risk_scorer",
    "play_recommender",
    "outcome_simulator",
    "drafter",
]

# The full analysis -> decision walk the routers traverse. ``gap_analysis`` and
# ``critic`` always run; the rest are gated by the roster. Order is dependency
# valid: retrieval grounds the run, risk scoring and gap analysis read evidence,
# the recommender needs the risk score, the simulator and drafter need the play.
_SEQUENCE = [
    "retrieval",
    "risk_scorer",
    "gap_analysis",
    "play_recommender",
    "outcome_simulator",
    "drafter",
    "critic",
]
_ALWAYS_ON = {"gap_analysis", "critic"}

# Loop bounds and trigger thresholds. Kept conservative so a normal run is a
# single forward pass (preserving latency and the existing trace), while the
# loops still fire for genuinely weak or under-grounded cases.
MAX_CLARIFY_LOOPS = 1
MAX_REPLAN_LOOPS = 2
REPLAN_CONFIDENCE_FLOOR = 0.45
CRITICAL_GAP_THRESHOLD = 2


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


# Per decision-point routing profiles, kept here only as a SAFE FALLBACK. The
# rosters are now first-class pack configuration (``decision_points[*].roster``
# and ``rationale`` in the domain YAML); the planner reads those at run time and
# only consults this table when a pack omits a roster for a decision point. Each
# entry names the specialist roster plus a one-line rationale; the roster is
# intersected with the registered pipeline so a profile can reference a
# specialist that is not installed without breaking the graph.
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
    "Standard decision flow: retrieve evidence, score risk, name information gaps, "
    "rank plays, simulate impact, and draft outreach."
)


def _runnable(caps: List[str]) -> List[str]:
    """Intersect a candidate roster with the installed pipeline, in dependency
    order, never returning an empty roster."""

    valid = {c for c in caps if c in _PIPELINE and AGENTS.has(c)}
    ordered = [c for c in _SEQUENCE if c in valid]
    if not ordered:
        # Never leave the run with no specialists: fall back to whatever is registered.
        ordered = [c for c in _SEQUENCE if c in _PIPELINE and AGENTS.has(c)]
    return ordered


def _deterministic_roster(pack: Any, decision_point: str) -> Tuple[List[str], str]:
    """Choose the specialist roster and rationale for a decision point.

    Configuration first: the candidate roster and rationale come from the domain
    pack (``decision_points[*].roster`` / ``rationale``). When the pack omits a
    roster the code-default ``_ROUTING`` profile is used, and finally the full
    flow. The roster is intersected with the registered pipeline so the graph
    topology stays stable while the active set varies per decision point.
    """

    pack_roster = pack.roster_for(decision_point)
    if pack_roster is not None:
        template = pack_roster
        rationale = (
            pack.rationale_for(decision_point)
            or (_ROUTING.get(decision_point) or {}).get("rationale")
            or _DEFAULT_RATIONALE
        )
    else:
        profile = _ROUTING.get(decision_point)
        template = profile["caps"] if profile else _FULL
        rationale = profile["rationale"] if profile else _DEFAULT_RATIONALE
    return _runnable(template), rationale


def _parse_llm_roster(text: str, candidate: List[str]) -> Tuple[List[str], str]:
    """Parse an LLM roster selection constrained to the candidate specialists.

    Recognizes the requested ``ROSTER:`` / ``RATIONALE:`` lines but also tolerates
    a free-form answer: any candidate capability key mentioned in the text is
    selected, kept in dependency order. Returns ``(roster, rationale)`` where an
    empty roster signals an unusable answer (caller falls back to deterministic).
    """

    roster_line = ""
    rationale = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        low = line.lower()
        if low.startswith("roster:"):
            roster_line = line.split(":", 1)[1]
        elif low.startswith("rationale:"):
            rationale = line.split(":", 1)[1].strip()
    haystack = (roster_line or text).lower()
    selected = {c for c in candidate if c in haystack}
    roster = [c for c in _SEQUENCE if c in selected]
    return roster, rationale


def _llm_select_roster_sync(
    pack: Any, decision_point: str, candidate: List[str], signal: Dict[str, Any]
) -> Optional[Tuple[List[str], str]]:
    """Online roster selection: let the planner LLM pick/order the roster.

    Returns ``None`` (so the caller uses the deterministic roster) in DEMO mode,
    when no live model is configured, on any error, or when the model's answer is
    not a usable roster. The selection is constrained to the candidate set and a
    play recommender is required, so the run can always produce a recommendation.
    """

    # Offline / DEMO is always deterministic: never depend on a canned model to
    # make the routing decision.
    if demo_mode_enabled():
        return None
    try:
        llm = get_llm()
    except Exception:  # noqa: BLE001
        return None
    if llm is None:
        return None

    dp = pack.decision_points.get(decision_point)
    dp_label = dp.label if dp else decision_point
    catalog_lines = []
    for cap in candidate:
        card = AGENTS.find(cap)
        catalog_lines.append(f"- {cap}: {card.description if card else ''}")
    catalog = "\n".join(catalog_lines)
    prompt = (
        f"{pack.planner_prompt}\n\n"
        f"Decision point: {dp_label}.\n"
        f"Account signal: {signal.get('content', '')}.\n\n"
        "Select which specialists to run for THIS case, choosing only from this "
        "candidate roster (you may drop a specialist that adds no value, but add "
        "none outside it):\n"
        f"{catalog}\n\n"
        "A play recommender must be included. Answer in exactly this format:\n"
        "ROSTER: <comma separated capability keys in run order>\n"
        "RATIONALE: <one sentence explaining the selection>"
    )
    try:
        result = llm.invoke(prompt)
        text = getattr(result, "content", result)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(text, str) or not text.strip():
        return None

    roster, rationale = _parse_llm_roster(text, candidate)
    roster = _runnable(roster)
    # A usable plan must be able to produce a play; otherwise fall back.
    if "play_recommender" not in roster:
        return None
    if not rationale:
        rationale = (
            pack.rationale_for(decision_point)
            or f"Planner selected {len(roster)} specialists for {dp_label}."
        )
    return roster, rationale


async def _select_roster(
    pack: Any, decision_point: str, signal: Dict[str, Any]
) -> Tuple[List[str], str, List[str], str]:
    """Resolve the run roster: LLM-selected online, deterministic otherwise.

    Returns ``(roster, rationale, skipped, source)`` where ``source`` is
    ``'llm'`` or ``'deterministic'`` and ``skipped`` lists the installed
    specialists that will not run.
    """

    candidate, det_rationale = _deterministic_roster(pack, decision_point)

    selection = await asyncio.to_thread(
        _llm_select_roster_sync, pack, decision_point, candidate, signal
    )
    if selection is not None:
        roster, rationale = selection
        source = "llm"
    else:
        roster, rationale = candidate, det_rationale
        source = "deterministic"

    installed = [c for c in _SEQUENCE if c in _PIPELINE and AGENTS.has(c)]
    skipped = [c for c in installed if c not in roster]
    return roster, rationale, skipped, source


# ---------------------------------------------------------------------------
# Routing primitives (the "supervisor"): pure functions of (current, roster).
# ---------------------------------------------------------------------------


def _is_active(node: str, capabilities: List[str]) -> bool:
    """True when a node should run: always-on, or selected into the roster."""

    return node in _ALWAYS_ON or node in capabilities


def _entry_node(capabilities: List[str]) -> str:
    """First active node in the sequence (where the planner hands off)."""

    for node in _SEQUENCE:
        if _is_active(node, capabilities):
            return node
    return "critic"


def _advance_from(node: str, capabilities: List[str]) -> str:
    """Next active node strictly after ``node`` in the sequence, else critic."""

    try:
        idx = _SEQUENCE.index(node)
    except ValueError:
        return "critic"
    for nxt in _SEQUENCE[idx + 1 :]:
        if _is_active(nxt, capabilities):
            return nxt
    return "critic"


def _projected_route(capabilities: List[str]) -> List[str]:
    """The node trajectory a single forward pass will take, for the trace/UI."""

    active = [n for n in _SEQUENCE if _is_active(n, capabilities)]
    return ["planner", *active, "policy_gate", "hitl_gate", "commit"]


async def planner_node(state: RunState) -> Dict[str, Any]:
    """Classify the signal, select specialists, and draft the plan."""

    domain = state.get("domain", "customer_success")
    signal = dict(state.get("signal") or {})
    pack = load_pack(domain)

    decision_point = _classify_decision_point(pack, signal)

    # Org-configured roster (Workflow Studio): when the org has pinned which
    # specialists run for this decision point, honor it verbatim and skip the
    # LLM/deterministic selection. Absent an override, behavior is unchanged.
    from app.packs.loader import roster_override_for

    override = roster_override_for(decision_point)
    if override:
        capabilities = _runnable(override)
        plan_rationale = "Roster configured for this org in Workflow Studio."
        skipped = [
            c for c in _SEQUENCE if c not in capabilities and c in _PIPELINE and AGENTS.has(c)
        ]
        plan_source = "org-config"
    else:
        # The roster IS the plan: online the LLM picks/orders it from the pack's
        # candidate roster; offline/DEMO or on failure a deterministic selection
        # is used. Execution below is driven by this roster (via ``capabilities``).
        capabilities, plan_rationale, skipped, plan_source = await _select_roster(
            pack, decision_point, signal
        )

    dp = pack.decision_points.get(decision_point)
    dp_label = dp.label if dp else decision_point

    route = _projected_route(capabilities)
    roster_text = ", ".join(capabilities) or "critic only"

    # First-class structured plan: what runs, what is skipped, why, and how it
    # was chosen. Surfaced in state and in the node.finished data so the trace
    # and graph can render the actual orchestration decision.
    plan: Dict[str, Any] = {
        "decision_point": decision_point,
        "roster": capabilities,
        "skipped": skipped,
        "rationale": plan_rationale,
        "source": plan_source,
    }
    routing = {
        "decision_point": decision_point,
        "roster": capabilities,
        "skipped": skipped,
        "always_on": sorted(_ALWAYS_ON),
        "route": route,
        "rationale": plan_rationale,
        "source": plan_source,
    }
    source_phrase = (
        "planner-selected" if plan_source == "llm" else "deterministically selected"
    )
    return {
        "decision_point": decision_point,
        "domain_pack_key": domain,
        "capabilities": capabilities,
        "plan": plan,
        "plan_rationale": plan_rationale,
        "routing": routing,
        "route": route,
        # Initialize the control-loop bookkeeping so downstream nodes can read it.
        "clarify_iterations": 0,
        "replan_iterations": 0,
        "needs_clarification": False,
        "replan_target": "",
        "gap_queries": [],
        "messages": [
            {
                "role": "planner",
                "content": (
                    f"Classified as {dp_label}; {source_phrase} {len(capabilities)} "
                    f"specialists ({roster_text}). {plan_rationale}"
                ),
            }
        ],
        "steps": [
            make_step(
                "planner",
                f"Classified decision point: {dp_label}; {source_phrase} "
                f"{len(capabilities)} specialists",
                {
                    "decision_point": decision_point,
                    "capabilities": capabilities + ["critic"],
                    "plan": plan,
                    "plan_rationale": plan_rationale,
                    "routing": routing,
                    "route": route,
                },
            )
        ],
    }


def _make_specialist_node(capability: str):
    """Wrap a registered specialist. With conditional routing an unselected
    specialist is never entered, but the guard keeps the node a safe no-op if it
    is ever reached out of band."""

    async def _node(state: RunState) -> Dict[str, Any]:
        caps = state.get("capabilities") or []
        if capability not in caps:
            return {}
        card = AGENTS.get(capability)
        return await card.node(dict(state))

    _node.__name__ = f"{capability}_node"
    return _node


async def gap_analysis_node(state: RunState) -> Dict[str, Any]:
    """First-class missing-information analysis (PDF workflow step 3).

    Names the concrete facts the evidence and account context do NOT contain,
    records them on state so the recommendation and critic can weigh them, and
    decides whether the engine should pause to gather more before recommending.
    When critical facts are absent (and the clarify budget is not spent) it asks
    the router to loop back to retrieval with gap-targeted sub-queries.
    """

    analysis = analyze_gaps(dict(state))
    missing = analysis["missing_information"]
    information_gaps = analysis["information_gaps"]
    critical = analysis["critical_gaps"]

    clarify_iters = int(state.get("clarify_iterations", 0))
    needs_clarification = (
        len(critical) >= CRITICAL_GAP_THRESHOLD and clarify_iters < MAX_CLARIFY_LOOPS
    )

    update: Dict[str, Any] = {
        "missing_information": missing,
        "information_gaps": information_gaps,
        "needs_clarification": needs_clarification,
    }

    if needs_clarification:
        gap_queries = gap_targeted_queries(critical)
        update["gap_queries"] = gap_queries
        update["clarify_iterations"] = clarify_iters + 1
        detail = (
            f"Found {len(missing)} information gap(s), {len(critical)} critical; "
            f"looping back to retrieve {len(gap_queries)} gap-targeted queries."
        )
    else:
        # Clear any prior gap queries so a later forward pass does not reuse them.
        update["gap_queries"] = []
        if critical:
            detail = (
                f"Found {len(missing)} information gap(s), {len(critical)} critical; "
                "proceeding (clarify budget spent or below threshold)."
            )
        else:
            detail = f"Found {len(missing)} information gap(s); evidence sufficient to proceed."

    update["messages"] = [{"role": "gap_analysis", "content": detail}]
    update["steps"] = [
        make_step(
            "gap_analysis",
            detail,
            {
                "missing_information": missing,
                "critical_gaps": critical,
                "needs_clarification": needs_clarification,
                "clarify_iteration": update.get("clarify_iterations", clarify_iters),
            },
        )
    ]
    return update


async def critic_node(state: RunState) -> Dict[str, Any]:
    """Run the critic specialist, then decide whether to replan.

    The critic always runs (faithfulness + self-consistency + calibration). On
    top of that, this node owns the replan decision: when the rationale is
    unfaithful or confidence is genuinely low, and the replan budget is not
    spent, it asks the router to route back to re-retrieve (thin / uncited
    evidence) or re-recommend (adequate evidence, weak pick).
    """

    card = AGENTS.get("critic")
    update = await card.node(dict(state))

    critic = dict(update.get("critic") or {})
    score = float(critic.get("confidence_reviewed", 0.7))
    faithful = bool(critic.get("faithful", True))
    grounded = int((critic.get("reflection") or {}).get("grounded_sources", 0))
    replan_iters = int(state.get("replan_iterations", 0))

    should_replan = (
        (not faithful or score < REPLAN_CONFIDENCE_FLOOR)
        and replan_iters < MAX_REPLAN_LOOPS
    )

    if should_replan:
        # Re-retrieve when the case is under-grounded; otherwise re-rank the play.
        target = "retrieval" if (not faithful or grounded < 2) else "play_recommender"
        reason = (
            "rationale not fully grounded; re-retrieving evidence"
            if target == "retrieval"
            else "confidence below floor; re-ranking the play"
        )
        critic["replan"] = {
            "triggered": True,
            "target": target,
            "iteration": replan_iters + 1,
            "reason": reason,
        }
        update["replan_target"] = target
        update["replan_iterations"] = replan_iters + 1
    else:
        target = ""
        critic["replan"] = {"triggered": False, "iteration": replan_iters}
        update["replan_target"] = ""

    update["critic"] = critic

    # Fold the replan decision into the critic's own trace step so the node's
    # node.finished event reflects what happens next, without adding a step.
    steps = list(update.get("steps") or [])
    if steps and isinstance(steps[-1], dict):
        last = dict(steps[-1])
        data = dict(last.get("data") or {})
        data["replan"] = critic["replan"]
        last["data"] = data
        if should_replan:
            last["summary"] = (
                f"{last.get('summary', '')} -> replan #{replan_iters + 1} ({target})"
            )
        steps[-1] = last
        update["steps"] = steps

    if should_replan:
        update.setdefault("messages", [])
        update["messages"] = list(update["messages"]) + [
            {
                "role": "critic",
                "content": f"Replanning (#{replan_iters + 1}): {reason}.",
            }
        ]

    return update


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


async def _effective_policies(domain: str, org_id: str):
    """Return the policy rules to enforce, honoring the org's saved overrides.

    Falls back to the base pack policies when no org is bound or the org has no
    override. Offline-safe: the overrides repository has an in-memory fallback,
    and any error degrades to the base policy set so a run never fails here.
    """

    if not org_id:
        return load_policies(domain)
    try:
        from app.packs.loader import effective_rules
        from app.policy.rules import parse_policies
        from app.repositories import pack_overrides as overrides_repo

        overrides = await overrides_repo.get_overrides(org_id, domain)
        if overrides.get("policies"):
            merged = effective_rules(domain, overrides)["policies"]
            rules = parse_policies(merged)
            if rules:
                return rules
    except Exception:  # noqa: BLE001 - never fail the run on override resolution
        pass
    return load_policies(domain)


async def policy_gate_node(state: RunState) -> Dict[str, Any]:
    """Evaluate the recommendation against the domain's declarative policies.

    Runs the pure, offline policy engine against the org's *effective* rules (the
    base pack merged with any override saved in the business-rules editor),
    attaches the gate results to the recommendation under
    ``recommendation['policy']`` (and to the trace), and forces human review when
    any failing gate requires approval. Existing critic fields are preserved;
    only ``requires_hitl`` is escalated, never relaxed.
    """

    domain = state.get("domain", "customer_success")
    org_id = state.get("org_id", "")
    recommendation = dict(state.get("recommendation") or {})

    rules = await _effective_policies(domain, org_id)
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
                org_id=state.get("org_id"),
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


# ---------------------------------------------------------------------------
# Router functions used by the conditional edges.
# ---------------------------------------------------------------------------


def _route_from_planner(state: RunState) -> str:
    return _entry_node(state.get("capabilities") or [])


def _route_forward(node: str) -> Callable[[RunState], str]:
    """Forward router for a specialist: advance to the next active node."""

    def _router(state: RunState) -> str:
        return _advance_from(node, state.get("capabilities") or [])

    return _router


def _route_from_gap(state: RunState) -> str:
    """Clarify loop: back to retrieval when more grounding is needed, else on."""

    if state.get("needs_clarification"):
        return "retrieval"
    return _advance_from("gap_analysis", state.get("capabilities") or [])


def _route_from_critic(state: RunState) -> str:
    """Replan loop: back to retrieval or play_recommender, else the policy gate."""

    target = state.get("replan_target") or ""
    if target in ("retrieval", "play_recommender"):
        return target
    return "policy_gate"


def _forward_targets(node: str) -> List[str]:
    """Possible next nodes for a forward router (for the conditional path map)."""

    idx = _SEQUENCE.index(node)
    return _SEQUENCE[idx + 1 :]


def build_graph(checkpointer: Any):
    """Build and compile the planner StateGraph with the given checkpointer.

    The topology is fixed (every node is added) but the edges are conditional, so
    the planner's roster decides which specialists actually execute and the
    clarify / replan loops decide when to revisit earlier nodes.
    """

    graph = StateGraph(RunState)

    graph.add_node("planner", planner_node)
    for capability in _PIPELINE:
        graph.add_node(capability, _make_specialist_node(capability))
    graph.add_node("gap_analysis", gap_analysis_node)
    graph.add_node("critic", critic_node)
    graph.add_node("policy_gate", policy_gate_node)
    graph.add_node("hitl_gate", hitl_gate_node)
    graph.add_node("commit", commit_node)

    graph.add_edge(START, "planner")

    # Planner hands off to the first active node in the sequence.
    graph.add_conditional_edges(
        "planner", _route_from_planner, {n: n for n in _SEQUENCE}
    )

    # Straight-through specialists advance to the next active node.
    for node in ("retrieval", "risk_scorer", "play_recommender", "outcome_simulator", "drafter"):
        graph.add_conditional_edges(
            node, _route_forward(node), {n: n for n in _forward_targets(node)}
        )

    # gap_analysis may loop back to retrieval (clarify) or advance.
    gap_targets = ["retrieval", *_forward_targets("gap_analysis")]
    graph.add_conditional_edges(
        "gap_analysis", _route_from_gap, {n: n for n in gap_targets}
    )

    # critic may loop back (replan) or fall through to the policy gate.
    graph.add_conditional_edges(
        "critic",
        _route_from_critic,
        {"retrieval": "retrieval", "play_recommender": "play_recommender", "policy_gate": "policy_gate"},
    )

    # Deterministic tail.
    graph.add_edge("policy_gate", "hitl_gate")
    graph.add_edge("hitl_gate", "commit")
    graph.add_edge("commit", END)

    return graph.compile(checkpointer=checkpointer)
