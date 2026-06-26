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
    domain: str
    account_id: str
    signal: Signal

    # --- planning ---
    plan: List[str]
    capabilities: List[str]
    decision_point: str
    domain_pack_key: str

    # --- blackboard (specialist outputs) ---
    evidence: List[Dict[str, Any]]
    risks: Dict[str, Any]
    risk_opportunity: Dict[str, Any]
    candidate_actions: List[Dict[str, Any]]
    simulation: Dict[str, Any]
    draft: Dict[str, Any]
    preferences: Dict[str, Any]
    similar_episodes: List[Dict[str, Any]]

    # --- outputs ---
    recommendation: Optional[Dict[str, Any]]
    critic: Dict[str, Any]
    episode_id: Optional[str]

    # --- accumulating channels ---
    steps: Annotated[List[Dict[str, Any]], operator.add]
    messages: Annotated[List[Dict[str, Any]], operator.add]
