"""Declarative guardrail / policy layer.

This package makes the platform's governance rules an explicit, inspectable
artifact rather than logic buried in prompts. A domain pack declares a list of
``policies`` (see :mod:`app.policy.rules`); the deterministic, offline engine in
:mod:`app.policy.engine` evaluates a recommendation against those rules and
returns a list of pass/fail/warn gate results that the planner attaches to the
recommendation and the UI renders as chips.

Nothing here calls an LLM or a database: evaluation is pure and reproducible so
the guardrails behave identically online and offline.
"""

from __future__ import annotations

from app.policy.engine import evaluate, evaluation_summary
from app.policy.rules import (
    PolicyRule,
    default_policies,
    load_policies,
    parse_policies,
)

__all__ = [
    "PolicyRule",
    "evaluate",
    "evaluation_summary",
    "default_policies",
    "load_policies",
    "parse_policies",
]
