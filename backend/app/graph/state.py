"""Typed run state for the LangGraph orchestration core.

The state is a TypedDict so it serializes cleanly through the checkpointer.
Accumulating channels (steps, messages) use additive reducers so each node can
append its own records without clobbering earlier nodes. All other channels are
last-write, which is safe because specialists run sequentially in the order the
planner selected.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class Signal(TypedDict, total=False):
    """A raw business signal that triggers a decision run."""

    type: str
    content: str


class RunState(TypedDict, total=False):
    """Shared blackboard passed between every node in the planner graph."""

    # --- request envelope ---
    run_id: str
    org_id: str
    domain: str
    account_id: str
    signal: Signal
    # A/B memory toggle: when true, the play recommender skips learned-preference
    # re-ranking and uses raw priors only (read by another slice's experiment).
    disable_memory: bool

    # --- planning ---
    # Structured, first-class plan: {decision_point, roster, skipped, rationale,
    # source}. The planner selects + orders the specialist roster (LLM-driven
    # online, deterministic offline) and execution is driven from it.
    plan: Dict[str, Any]
    capabilities: List[str]
    decision_point: str
    domain_pack_key: str
    plan_rationale: str
    routing: Dict[str, Any]
    route: List[str]

    # --- blackboard (specialist outputs) ---
    evidence: List[Dict[str, Any]]
    risks: Dict[str, Any]
    risk_opportunity: Dict[str, Any]
    candidate_actions: List[Dict[str, Any]]
    simulation: Dict[str, Any]
    draft: Dict[str, Any]
    preferences: Dict[str, Any]
    similar_episodes: List[Dict[str, Any]]

    # --- missing-information analysis (PDF step 3) ---
    missing_information: List[Dict[str, Any]]
    information_gaps: List[str]

    # --- control-loop bookkeeping (clarify + replan) ---
    needs_clarification: bool
    clarify_iterations: int
    replan_iterations: int
    replan_target: str
    gap_queries: List[str]

    # --- outputs ---
    recommendation: Optional[Dict[str, Any]]
    critic: Dict[str, Any]
    episode_id: Optional[str]

    # --- accumulating channels ---
    steps: Annotated[List[Dict[str, Any]], operator.add]
    messages: Annotated[List[Dict[str, Any]], operator.add]
