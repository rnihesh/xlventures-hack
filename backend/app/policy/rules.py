"""Policy rule model and loading.

A policy rule is a small, declarative record a domain pack author writes in YAML.
The engine interprets the ``type`` and ``condition`` to decide whether a given
recommendation satisfies the rule. Keeping rules as data (not code) means a new
guardrail is a few lines of YAML, and the full rule set is inspectable through
the ``GET /policy/{domain}`` endpoint and the policy panel in the UI.

Supported rule ``type`` values (each maps to an evaluator in
:mod:`app.policy.engine`):

* ``discount_cap``            condition: ``{max_pct: float}``
* ``cooldown_window``         condition: ``{min_days: int, applies_to_actions: [str]}``
* ``action_requires_approval`` condition: ``{actions: [str]}``
* ``confidence_floor``        condition: ``{min: float}``
* ``field_threshold``         condition: ``{field, op, value, on_violation?}``

Unknown types degrade safely to a passing "not enforced" gate, so a typo in a
pack never breaks a run.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class PolicyRule(BaseModel):
    """A single declarative guardrail.

    Attributes
    ----------
    id:
        Stable identifier, surfaced in gate results and the trace.
    description:
        Human readable statement of the rule, shown verbatim in the UI.
    type:
        Selects which evaluator interprets ``condition``.
    condition:
        Type specific parameters (e.g. ``{"max_pct": 15}``).
    severity:
        ``low`` | ``medium`` | ``high``; advisory weighting for the UI.
    requires_approval:
        When the rule is not satisfied, force the run through human review
        instead of allowing an auto-approval.
    """

    model_config = {"extra": "allow"}

    id: str
    description: str = ""
    type: str = "field_threshold"
    condition: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "medium"
    requires_approval: bool = False

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "PolicyRule":
        """Build a rule from a loosely typed pack dict, tolerating aliases."""

        data = dict(raw or {})
        # Accept a couple of friendly aliases so pack authoring stays forgiving.
        if "id" not in data and "key" in data:
            data["id"] = data["key"]
        if "condition" not in data and "spec" in data:
            data["condition"] = data["spec"]
        if "requires_approval" not in data and "needs_approval" in data:
            data["requires_approval"] = data["needs_approval"]

        # Narrative pack schema (key/label/rule/severity:hard|soft/
        # requires_approval_from). Map it onto the structured fields so these
        # guardrails surface a real description and route through the engine as
        # advisory gates instead of an empty, misleading "not configured" rule.
        if "description" not in data or not data.get("description"):
            if data.get("label"):
                data["description"] = data["label"]
            elif data.get("rule"):
                data["description"] = data["rule"]
        if "requires_approval" not in data and "requires_approval_from" in data:
            data["requires_approval"] = bool(data.get("requires_approval_from"))
        if "type" not in data and "condition" not in data and "spec" not in data:
            # No machine-checkable condition: treat as a human-judgment guardrail.
            data["type"] = "advisory"
        # Normalize narrative severities to the engine's low|medium|high band.
        severity = str(data.get("severity", "")).lower()
        if severity in ("hard", "critical", "blocker"):
            data["severity"] = "high"
        elif severity in ("soft", "advisory", "info"):
            data["severity"] = "low"
        return cls(**data)


def parse_policies(raw_policies: Any) -> List[PolicyRule]:
    """Coerce a pack's raw ``policies`` value into validated rules.

    Tolerates ``None``, a list of dicts, or already-built rules. Any individual
    malformed entry is skipped rather than failing the whole load.
    """

    if not raw_policies:
        return []

    rules: List[PolicyRule] = []
    for entry in raw_policies:
        try:
            if isinstance(entry, PolicyRule):
                rules.append(entry)
            elif isinstance(entry, dict):
                rules.append(PolicyRule.from_raw(entry))
        except Exception:  # noqa: BLE001 - never let one bad rule break the set
            continue
    return rules


# ---------------------------------------------------------------------------
# Built-in fallbacks. Used only when a pack declares no ``policies`` section
# (e.g. the generic minimal pack), so the guardrail layer is never empty and
# the demo is deterministic offline.
# ---------------------------------------------------------------------------
_DEFAULT_POLICIES: Dict[str, List[Dict[str, Any]]] = {
    "customer_success": [
        {
            "id": "discount_cap_15",
            "description": "Retention discounts above 15% require deal-desk approval.",
            "type": "discount_cap",
            "condition": {"max_pct": 15},
            "severity": "high",
            "requires_approval": True,
        },
        {
            "id": "exec_escalation_signoff",
            "description": "Executive escalations require CS manager sign-off.",
            "type": "action_requires_approval",
            "condition": {"actions": ["open_executive_escalation"]},
            "severity": "high",
            "requires_approval": True,
        },
        {
            "id": "outreach_cooldown",
            "description": "No new customer outreach within 7 days of the last touch.",
            "type": "cooldown_window",
            "condition": {
                "min_days": 7,
                "applies_to_actions": [
                    "schedule_executive_business_review",
                    "launch_adoption_campaign",
                    "open_executive_escalation",
                ],
            },
            "severity": "medium",
            "requires_approval": False,
        },
    ],
    "saas_sales": [
        {
            "id": "discount_cap_20",
            "description": "Proposal discounts above 20% require sales manager approval.",
            "type": "discount_cap",
            "condition": {"max_pct": 20},
            "severity": "high",
            "requires_approval": True,
        },
        {
            "id": "closing_proposal_signoff",
            "description": "Sending a closing proposal requires manager sign-off.",
            "type": "action_requires_approval",
            "condition": {"actions": ["send_proposal"]},
            "severity": "high",
            "requires_approval": True,
        },
    ],
}


def default_policies(domain: str) -> List[PolicyRule]:
    """Return the built-in fallback policy set for a domain (possibly empty)."""

    return parse_policies(_DEFAULT_POLICIES.get(domain, []))


def load_policies(domain: str) -> List[PolicyRule]:
    """Load a domain's declared policies, falling back to the built-ins.

    Reads the ``policies`` section from the domain pack YAML (the pack model
    allows extra fields, so the section is available as an attribute). Any error
    degrades to the deterministic built-in set so the layer is never empty.
    """

    try:
        from app.packs.loader import load_pack

        pack = load_pack(domain)
        raw = getattr(pack, "policies", None)
        if raw is None:
            extra = getattr(pack, "model_extra", None) or {}
            raw = extra.get("policies")
        rules = parse_policies(raw)
        if rules:
            return rules
    except Exception:  # noqa: BLE001 - fall through to defaults
        pass
    return default_policies(domain)
