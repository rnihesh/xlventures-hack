"""LangGraph planner graph for the walking skeleton.

A real, end to end multi node flow:

    planner -> retrieve -> analyze -> recommend -> critic -> END

Each node appends a step record to state. The planner and recommend nodes use
`get_llm`, with graceful fallbacks so the graph runs even without an LLM key.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from langgraph.graph import END, START, StateGraph

from app.deps import get_llm
from app.explain.recommendation import build_recommendation
from app.graph.state import RunState


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step(node: str, summary: str, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "node": node,
        "summary": summary,
        "ts": _now_iso(),
        "data": data or {},
    }


def _safe_llm_text(prompt: str, fallback: str) -> str:
    """Invoke the LLM for a short string, falling back on any error."""

    try:
        llm = get_llm()
    except Exception:
        return fallback
    if llm is None:
        return fallback
    try:
        result = llm.invoke(prompt)
        text = getattr(result, "content", result)
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:
        return fallback
    return fallback


def planner_node(state: RunState) -> Dict[str, Any]:
    """Decompose the signal into a short ordered plan."""

    account_id = state.get("account_id", "unknown-account")
    signal = state.get("signal") or {}
    signal_content = signal.get("content", "Churn risk signal detected.")

    prompt = (
        "You are a planning supervisor for a Customer Success decision engine. "
        f"Account: {account_id}. Signal: {signal_content}. "
        "List 4 short imperative steps (retrieve evidence, assess risk, "
        "recommend a play, critique). Reply as a newline separated list."
    )
    fallback = (
        "Retrieve account evidence\n"
        "Assess churn risk and opportunity\n"
        "Recommend the next best action\n"
        "Critique the recommendation for faithfulness"
    )
    raw = _safe_llm_text(prompt, fallback)
    plan: List[str] = [line.strip(" -*0123456789.") for line in raw.splitlines() if line.strip()]
    if not plan:
        plan = [s.strip() for s in fallback.splitlines()]

    return {
        "plan": plan,
        "messages": [{"role": "planner", "content": "Plan drafted."}],
        "steps": [_step("planner", "Drafted a 4 step plan", {"plan": plan})],
    }


def retrieve_node(state: RunState) -> Dict[str, Any]:
    """Return a couple of plausible, span citable evidence snippets."""

    account_id = state.get("account_id", "unknown-account")
    snippet_a = (
        "Product usage for this account dropped 38% quarter over quarter, with "
        "weekly active seats falling from 120 to 74."
    )
    snippet_b = (
        "The economic buyer has not attended a business review in 2 quarters and "
        "the renewal is 95 days out."
    )
    evidence = [
        {
            "claim": "Usage is declining sharply ahead of renewal.",
            "source_id": f"telemetry:{account_id}:q-usage",
            "source_type": "product_telemetry",
            "snippet": snippet_a,
            "span": {"start": 0, "end": 38},
        },
        {
            "claim": "Executive sponsor engagement has lapsed.",
            "source_id": f"crm:{account_id}:engagement",
            "source_type": "crm_activity",
            "snippet": snippet_b,
            "span": {"start": 0, "end": 49},
        },
    ]
    return {
        "evidence": evidence,
        "steps": [
            _step(
                "retrieve",
                f"Retrieved {len(evidence)} evidence snippets",
                {"evidence_count": len(evidence)},
            )
        ],
    }


def analyze_node(state: RunState) -> Dict[str, Any]:
    """Classify the situation as a risk or opportunity."""

    risk = {
        "type": "risk",
        "summary": (
            "Declining usage plus a disengaged executive sponsor inside the "
            "renewal window indicates compounding churn risk."
        ),
    }
    return {
        "risk_opportunity": risk,
        "steps": [_step("analyze", "Classified as churn risk", risk)],
    }


def recommend_node(state: RunState) -> Dict[str, Any]:
    """Produce the Explainable Recommendation Object."""

    try:
        llm = get_llm()
    except Exception:
        llm = None
    recommendation = build_recommendation(dict(state), llm)
    return {
        "recommendation": recommendation,
        "messages": [{"role": "recommender", "content": recommendation["action"]["title"]}],
        "steps": [
            _step(
                "recommend",
                f"Recommended action: {recommendation['action']['key']}",
                {"action_key": recommendation["action"]["key"]},
            )
        ],
    }


def critic_node(state: RunState) -> Dict[str, Any]:
    """Verify faithfulness and confirm whether HITL is required."""

    recommendation = state.get("recommendation") or {}
    confidence = (recommendation.get("confidence") or {}).get("score", 0.0)
    evidence = recommendation.get("evidence") or []
    faithful = len(evidence) > 0
    requires_hitl = (
        recommendation.get("risk_opportunity", {}).get("type") == "risk"
        or confidence < 0.85
    )
    critic = {
        "faithful": faithful,
        "confidence_reviewed": confidence,
        "requires_hitl": requires_hitl,
        "verdict": "approved_for_review" if faithful else "needs_replan",
    }
    return {
        "critic": critic,
        "messages": [{"role": "critic", "content": critic["verdict"]}],
        "steps": [_step("critic", "Critiqued recommendation", critic)],
    }


def build_graph(checkpointer: Any):
    """Build and compile the planner StateGraph with the given checkpointer."""

    graph = StateGraph(RunState)

    graph.add_node("planner", planner_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("recommend", recommend_node)
    graph.add_node("critic", critic_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "retrieve")
    graph.add_edge("retrieve", "analyze")
    graph.add_edge("analyze", "recommend")
    graph.add_edge("recommend", "critic")
    graph.add_edge("critic", END)

    return graph.compile(checkpointer=checkpointer)
