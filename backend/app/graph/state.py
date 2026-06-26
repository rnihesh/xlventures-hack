"""Typed run state for the LangGraph orchestration core.

The state is a TypedDict so it serializes cleanly through the checkpointer.
Accumulating channels (steps, messages) use additive reducers so each node can
append its own records without clobbering earlier nodes.
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

    run_id: str
    domain: str
    account_id: str
    signal: Signal
    plan: List[str]
    steps: Annotated[List[Dict[str, Any]], operator.add]
    evidence: List[Dict[str, Any]]
    risk_opportunity: Dict[str, Any]
    recommendation: Optional[Dict[str, Any]]
    critic: Dict[str, Any]
    messages: Annotated[List[Dict[str, Any]], operator.add]
