"""Unit tests for the deterministic policy engine.

Exercises the pass / fail / warn logic of each evaluator directly through
``evaluate`` (pure, offline, no LLM, no DB), plus the per-gate
``requires_approval`` derivation and the aggregate summary.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.policy.engine import evaluate, evaluation_summary
from app.policy.rules import PolicyRule


def _gate(results: List[Dict[str, Any]], rule_id: str) -> Dict[str, Any]:
    """Return the single gate result for a given rule id."""

    matches = [r for r in results if r["rule_id"] == rule_id]
    assert matches, f"no gate produced for rule {rule_id}"
    return matches[0]


def test_discount_cap_pass_and_fail() -> None:
    """The discount cap passes within the limit and fails above it."""

    rule = PolicyRule(
        id="discount_cap_15",
        description="Discounts above 15% need sign-off.",
        type="discount_cap",
        condition={"max_pct": 15},
        severity="high",
        requires_approval=True,
    )

    # Within cap -> pass, and not holding the run.
    ok = evaluate({"action": {"key": "x"}, "discount_pct": 10}, {}, [rule])
    gate = _gate(ok, "discount_cap_15")
    assert gate["status"] == "pass"
    assert gate["requires_approval"] is False

    # No discount proposed -> still a pass (cap not engaged).
    none = evaluate({"action": {"key": "x"}}, {}, [rule])
    assert _gate(none, "discount_cap_15")["status"] == "pass"

    # Over cap -> fail, and because the rule requires approval the gate holds.
    bad = evaluate({"action": {"key": "x"}, "discount_pct": 25}, {}, [rule])
    gate = _gate(bad, "discount_cap_15")
    assert gate["status"] == "fail"
    assert gate["requires_approval"] is True


def test_confidence_floor_warns_below_minimum() -> None:
    """A confidence below the floor warns; at or above the floor passes."""

    rule = PolicyRule(
        id="confidence_floor",
        description="Low-confidence actions need review.",
        type="confidence_floor",
        condition={"min": 0.85},
        severity="medium",
        requires_approval=False,
    )

    low = evaluate({"action": {"key": "x"}, "confidence": {"score": 0.5}}, {}, [rule])
    assert _gate(low, "confidence_floor")["status"] == "warn"

    high = evaluate({"action": {"key": "x"}, "confidence": {"score": 0.9}}, {}, [rule])
    assert _gate(high, "confidence_floor")["status"] == "pass"


def test_action_requires_approval_warns_for_gated_action() -> None:
    """A gated action warns; an ungated action passes."""

    rule = PolicyRule(
        id="exec_escalation_signoff",
        description="Executive escalations require sign-off.",
        type="action_requires_approval",
        condition={"actions": ["open_executive_escalation"]},
        severity="high",
        requires_approval=True,
    )

    gated = evaluate({"action": {"key": "open_executive_escalation"}}, {}, [rule])
    gate = _gate(gated, "exec_escalation_signoff")
    assert gate["status"] == "warn"
    # Warn on an approval-required rule means the gate is actively holding.
    assert gate["requires_approval"] is True

    other = evaluate({"action": {"key": "launch_adoption_campaign"}}, {}, [rule])
    assert _gate(other, "exec_escalation_signoff")["status"] == "pass"


def test_cooldown_window_warns_inside_window() -> None:
    """Outreach inside the cooldown window warns; clear of it passes."""

    rule = PolicyRule(
        id="outreach_cooldown",
        description="No outreach within 7 days of the last touch.",
        type="cooldown_window",
        condition={"min_days": 7, "applies_to_actions": ["launch_adoption_campaign"]},
        severity="medium",
        requires_approval=False,
    )

    rec = {"action": {"key": "launch_adoption_campaign"}}

    inside = evaluate(rec, {"days_since_last_outreach": 2}, [rule])
    assert _gate(inside, "outreach_cooldown")["status"] == "warn"

    clear = evaluate(rec, {"days_since_last_outreach": 30}, [rule])
    assert _gate(clear, "outreach_cooldown")["status"] == "pass"

    # A non-matching action is unaffected by the cooldown.
    skip = evaluate({"action": {"key": "monitor_no_action"}}, {"days_since_last_outreach": 1}, [rule])
    assert _gate(skip, "outreach_cooldown")["status"] == "pass"


def test_unknown_rule_type_is_non_blocking() -> None:
    """An unknown rule type degrades to a passing, non-enforced gate."""

    rule = PolicyRule(id="mystery", description="?", type="not_a_real_type", condition={})
    results = evaluate({"action": {"key": "x"}}, {}, [rule])
    gate = _gate(results, "mystery")
    assert gate["status"] == "pass"
    assert gate["requires_approval"] is False


def test_evaluation_summary_counts_and_approval_flag() -> None:
    """The summary tallies pass/warn/fail and reflects any holding gate."""

    rules = [
        PolicyRule(
            id="cap",
            type="discount_cap",
            condition={"max_pct": 15},
            requires_approval=True,
        ),
        PolicyRule(
            id="floor",
            type="confidence_floor",
            condition={"min": 0.85},
            requires_approval=False,
        ),
    ]
    # Over-cap discount (fail, holding) + low confidence (warn, not holding).
    rec = {"action": {"key": "x"}, "discount_pct": 30, "confidence": {"score": 0.4}}
    results = evaluate(rec, {}, rules)
    summary = evaluation_summary(results)

    assert summary["total"] == 2
    assert summary["failed"] == 1
    assert summary["warned"] == 1
    assert summary["passed"] == 0
    assert summary["requires_approval"] is True

    # An all-clear set requires no approval.
    clear = evaluate({"action": {"key": "x"}, "confidence": {"score": 0.95}}, {}, rules)
    assert evaluation_summary(clear)["requires_approval"] is False
