"""Deterministic, offline policy evaluation engine.

``evaluate`` takes a recommendation, the account it concerns, and the list of
:class:`~app.policy.rules.PolicyRule` for the domain, and returns one gate result
per rule::

    {
        "rule_id": str,
        "description": str,
        "status": "pass" | "fail" | "warn",
        "detail": str,
        "severity": str,
        "requires_approval": bool,   # True only when this gate is holding
    }

The engine is pure and contains no I/O, no LLM, and no randomness: the same
inputs always produce the same gates. Each rule ``type`` maps to a small bespoke
evaluator; unknown types resolve to a passing "not enforced" gate so a bad pack
never breaks a run.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.policy.rules import PolicyRule

# A gate is satisfied (pass), violated outright (fail), or flagged (warn).
Status = str

_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DISCOUNT_HINT_RE = re.compile(r"discount|concession|save|credit|rebate|waiver", re.I)


def _to_float(value: Any) -> Optional[float]:
    """Best-effort float coercion; returns None when not numeric."""

    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _discount_pct(recommendation: Dict[str, Any]) -> float:
    """Derive the discount percentage a recommendation implies.

    Prefers explicit numeric fields; otherwise, only when the chosen action
    reads as a concession, parses the first ``NN%`` out of its text. Returns 0
    when no discount is implied (the common case), which keeps caps quiet for
    non-pricing plays.
    """

    rec = recommendation or {}
    action = rec.get("action") or {}

    for candidate in (
        rec.get("discount_pct"),
        (rec.get("concession") or {}).get("discount_pct")
        if isinstance(rec.get("concession"), dict)
        else None,
        action.get("discount_pct"),
    ):
        num = _to_float(candidate)
        if num is not None:
            return num

    key = str(action.get("key", ""))
    text = " ".join(
        str(part or "")
        for part in (action.get("title"), action.get("description"))
    )
    if _DISCOUNT_HINT_RE.search(key) or _DISCOUNT_HINT_RE.search(text):
        match = _PCT_RE.search(text)
        if match:
            return float(match.group(1))
    return 0.0


def _account_field(account: Dict[str, Any], name: str) -> Any:
    """Read a field from the account, checking the nested profile too."""

    acc = account or {}
    if name in acc:
        return acc[name]
    profile = acc.get("profile")
    if isinstance(profile, dict) and name in profile:
        return profile[name]
    return None


def _build_context(
    recommendation: Dict[str, Any], account: Dict[str, Any]
) -> Dict[str, Any]:
    """Flatten the inputs into the value space the evaluators read."""

    rec = recommendation or {}
    acc = account or {}
    action = rec.get("action") or {}
    confidence = rec.get("confidence") or {}
    risk = rec.get("risk_opportunity") or {}

    return {
        "action_key": str(action.get("key", "")),
        "action_title": str(action.get("title", "")),
        "discount_pct": _discount_pct(rec),
        "confidence": _to_float(confidence.get("score")),
        "risk_type": str(risk.get("type", "")),
        "account": {
            "account_id": str(acc.get("account_id", "")),
            "arr": _to_float(_account_field(acc, "arr")),
            "risk_level": str(_account_field(acc, "risk_level") or ""),
            "health_score": _to_float(_account_field(acc, "health_score")),
            "renewal_in_days": _to_float(_account_field(acc, "renewal_in_days")),
            "days_since_last_outreach": _to_float(
                _account_field(acc, "days_since_last_outreach")
            ),
        },
    }


def _resolve_path(context: Dict[str, Any], path: str) -> Any:
    """Resolve a dotted path (e.g. ``account.arr``) within the context."""

    cur: Any = context
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


# ---------------------------------------------------------------------------
# Evaluators. Each returns (status, detail). The engine derives the per-gate
# ``requires_approval`` flag from the rule and whether the gate passed.
# ---------------------------------------------------------------------------
def _eval_discount_cap(
    ctx: Dict[str, Any], rule: PolicyRule
) -> Tuple[Status, str]:
    max_pct = _to_float(rule.condition.get("max_pct"))
    discount = _to_float(ctx.get("discount_pct")) or 0.0
    if max_pct is None:
        return "pass", "No discount cap configured."
    if discount <= max_pct:
        if discount <= 0:
            return "pass", f"No discount proposed; the {max_pct:.0f}% cap is not engaged."
        return "pass", f"Proposed discount {discount:.0f}% is within the {max_pct:.0f}% cap."
    return (
        "fail",
        f"Proposed discount {discount:.0f}% exceeds the {max_pct:.0f}% cap and needs sign-off.",
    )


def _eval_cooldown_window(
    ctx: Dict[str, Any], rule: PolicyRule
) -> Tuple[Status, str]:
    applies_to = rule.condition.get("applies_to_actions") or []
    if applies_to and ctx.get("action_key") not in applies_to:
        return "pass", "Not an outreach action; cooldown does not apply."
    min_days = _to_float(rule.condition.get("min_days")) or 0.0
    days = _to_float(ctx["account"].get("days_since_last_outreach"))
    if days is None:
        return "pass", "No recent outreach on record; cooldown window is clear."
    if days < min_days:
        return (
            "warn",
            f"Last outreach was {days:.0f}d ago, inside the {min_days:.0f}d cooldown window.",
        )
    return "pass", f"Last outreach was {days:.0f}d ago, clear of the {min_days:.0f}d cooldown."


def _eval_action_requires_approval(
    ctx: Dict[str, Any], rule: PolicyRule
) -> Tuple[Status, str]:
    actions = rule.condition.get("actions") or []
    if ctx.get("action_key") in actions:
        return (
            "warn",
            f"Action '{ctx.get('action_title') or ctx.get('action_key')}' is gated and needs sign-off.",
        )
    return "pass", "Chosen action is not on the approval-gated list."


def _eval_confidence_floor(
    ctx: Dict[str, Any], rule: PolicyRule
) -> Tuple[Status, str]:
    minimum = _to_float(rule.condition.get("min"))
    conf = _to_float(ctx.get("confidence"))
    if minimum is None:
        return "pass", "No confidence floor configured."
    if conf is None:
        return "pass", "No confidence score available to check."
    if conf < minimum:
        return (
            "warn",
            f"Confidence {conf * 100:.0f}% is below the {minimum * 100:.0f}% review floor.",
        )
    return "pass", f"Confidence {conf * 100:.0f}% clears the {minimum * 100:.0f}% floor."


_OPS: Dict[str, Callable[[float, float], bool]] = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


def _eval_field_threshold(
    ctx: Dict[str, Any], rule: PolicyRule
) -> Tuple[Status, str]:
    """Generic guardrail: trips when ``field op value`` holds.

    ``on_violation`` (``warn`` default, or ``fail``) sets the tripped status.
    """

    field = rule.condition.get("field")
    op = str(rule.condition.get("op", "")).lower()
    threshold = _to_float(rule.condition.get("value"))
    actual = _to_float(_resolve_path(ctx, field)) if field else None
    fn = _OPS.get(op)
    if field is None or fn is None or threshold is None:
        return "pass", "Threshold guard not fully configured; skipped."
    if actual is None:
        return "pass", f"No value for '{field}' to evaluate."
    tripped = fn(actual, threshold)
    if tripped:
        status = "fail" if str(rule.condition.get("on_violation", "warn")) == "fail" else "warn"
        return status, f"'{field}' is {actual:g} ({op} {threshold:g}); guard tripped."
    return "pass", f"'{field}' is {actual:g}; within guard limits."


_EVALUATORS: Dict[str, Callable[[Dict[str, Any], PolicyRule], Tuple[Status, str]]] = {
    "discount_cap": _eval_discount_cap,
    "cooldown_window": _eval_cooldown_window,
    "action_requires_approval": _eval_action_requires_approval,
    "confidence_floor": _eval_confidence_floor,
    "field_threshold": _eval_field_threshold,
}


def evaluate(
    recommendation: Dict[str, Any],
    account: Optional[Dict[str, Any]],
    pack_policies: List[PolicyRule],
) -> List[Dict[str, Any]]:
    """Evaluate a recommendation against a domain's policy rules.

    Returns one gate result per rule. Pure and deterministic: never raises, never
    performs I/O. A gate carries ``requires_approval=True`` only when its rule
    requires approval *and* the gate did not pass, i.e. it is actively holding
    the recommendation for human review.
    """

    ctx = _build_context(recommendation or {}, account or {})
    results: List[Dict[str, Any]] = []

    for rule in pack_policies or []:
        evaluator = _EVALUATORS.get(rule.type)
        if evaluator is None:
            status, detail = "pass", f"Rule type '{rule.type}' is not enforced by this engine."
        else:
            try:
                status, detail = evaluator(ctx, rule)
            except Exception:  # noqa: BLE001 - a broken rule must not break the run
                status, detail = "pass", "Rule could not be evaluated; treated as non-blocking."

        holding = bool(rule.requires_approval) and status != "pass"
        results.append(
            {
                "rule_id": rule.id,
                "description": rule.description,
                "status": status,
                "detail": detail,
                "severity": rule.severity,
                "requires_approval": holding,
            }
        )

    return results


def evaluation_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate gate results for quick consumption by the planner and UI."""

    results = results or []
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.get("status") == "pass"),
        "warned": sum(1 for r in results if r.get("status") == "warn"),
        "failed": sum(1 for r in results if r.get("status") == "fail"),
        "requires_approval": any(r.get("requires_approval") for r in results),
    }
