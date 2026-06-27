"""Pydantic models for a Domain Pack.

A Domain Pack is the unit of reusability for the platform: every domain specific
behavior (signals, eligible actions, decision points, KPIs, playbooks, planner
prompt) lives in a YAML file and is loaded into these models. The engine and the
specialist agents read a DomainPack as configuration, so a new vertical is a
folder of data, not a code change.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, Field, ValidationError


class Persona(BaseModel):
    """A role the platform serves within a domain."""

    key: str
    label: str = ""
    description: str = ""
    goals: List[str] = Field(default_factory=list)


class Signal(BaseModel):
    """A raw business signal the engine can react to."""

    key: str
    label: str = ""
    source_type: str = ""


class DecisionPoint(BaseModel):
    """A classified situation that maps signals to a primary KPI and persona.

    ``roster`` and ``rationale`` make orchestration configurable: they name the
    candidate specialist roster (and why) the planner should run for this
    decision point. When omitted the planner falls back to safe code defaults, so
    a pack that does not declare a roster still runs the full pipeline.

    ``when`` is a plain-language description of when this decision point fires (the
    business trigger), complementing the machine-readable ``trigger_signals``. It
    is optional and defaulted so existing packs keep parsing unchanged.
    """

    label: str = ""
    description: str = ""
    when: str = ""
    trigger_signals: List[str] = Field(default_factory=list)
    primary_kpi: str = ""
    default_persona: str = ""
    roster: List[str] = Field(default_factory=list)
    rationale: str = ""


class Action(BaseModel):
    """An eligible play the recommender may propose.

    ``base_value``, ``effort``, and ``eligible_points`` move the recommender's
    action economics into the pack (config, not code): the expected-value prior
    (0..1), the relative execution effort (0..1), and the decision points this
    action is eligible for. All are optional so a pack that omits them keeps the
    recommender's built-in safe defaults.
    """

    key: str
    title: str = ""
    description: str = ""
    eligibility: str = ""
    base_value: Optional[float] = None
    effort: Optional[float] = None
    eligible_points: List[str] = Field(default_factory=list)


class Playbook(BaseModel):
    """An ordered set of steps tied to a decision point."""

    key: str
    name: str = ""
    decision_point: str = ""
    steps: List[str] = Field(default_factory=list)


class KPI(BaseModel):
    """A measurable outcome metric for the domain."""

    key: str
    label: str = ""
    description: str = ""
    unit: str = ""
    target: str = ""


class RetrievalSource(BaseModel):
    """A source type the retrieval layer can ground evidence against."""

    key: str
    label: str = ""
    source_type: str = ""


# ---------------------------------------------------------------------------
# Narrative / domain-understanding models.
#
# These make the business domain legible to a human (and a judge): the operating
# process, the customer journey, and the success metrics that define winning.
# They are pure documentation: the engine does not branch on them, so every
# field is optional and defaulted and an existing pack that omits them parses and
# runs exactly as before.
# ---------------------------------------------------------------------------


class ProcessStage(BaseModel):
    """An ordered stage of the domain's business process (how the team operates)."""

    key: str = ""
    name: str = ""
    description: str = ""
    goal: str = ""


class JourneyStage(BaseModel):
    """A stage of the customer (or account) journey through the lifecycle."""

    key: str = ""
    name: str = ""
    description: str = ""
    goal: str = ""
    risks: List[str] = Field(default_factory=list)


class SuccessMetric(BaseModel):
    """A business success metric: what it measures and the target or benchmark.

    This is the business-legible companion to :class:`KPI`. ``definition`` states
    what the metric measures in plain language; ``target`` is this org's goal and
    ``benchmark`` is the typical industry reference point, so the platform can
    show where intervention should move the number.
    """

    key: str = ""
    name: str = ""
    definition: str = ""
    target: str = ""
    benchmark: str = ""


class DomainPack(BaseModel):
    """A fully parsed, validated domain configuration."""

    model_config = {"extra": "allow"}

    domain: str
    display_name: str = ""
    # One-line domain summary / persona descriptor for the overview header.
    tagline: str = ""
    personas: List[Persona] = Field(default_factory=list)
    signals: List[Signal] = Field(default_factory=list)
    decision_points: Dict[str, DecisionPoint] = Field(default_factory=dict)
    actions: List[Action] = Field(default_factory=list)
    playbooks: List[Playbook] = Field(default_factory=list)
    kpis: List[KPI] = Field(default_factory=list)
    retrieval_sources: List[RetrievalSource] = Field(default_factory=list)
    # Narrative domain-understanding fields (all optional, additive). They make
    # the business legible without changing any engine behavior.
    business_process: List[ProcessStage] = Field(default_factory=list)
    customer_journey: List[JourneyStage] = Field(default_factory=list)
    success_metrics: List[SuccessMetric] = Field(default_factory=list)
    planner_prompt: str = ""

    # ------------------------------------------------------------------
    # Convenience lookups used by the planner and specialist agents.
    # ------------------------------------------------------------------
    def action_by_key(self, key: str) -> Optional[Action]:
        """Return the action with this key, or None."""

        for action in self.actions:
            if action.key == key:
                return action
        return None

    def kpi_by_key(self, key: str) -> Optional[KPI]:
        """Return the KPI with this key, or None."""

        for kpi in self.kpis:
            if kpi.key == key:
                return kpi
        return None

    def roster_for(self, decision_point: str) -> Optional[List[str]]:
        """Return the configured candidate roster for a decision point, or None.

        None means the pack did not declare one, so the planner should use its
        code default. An empty list is treated the same as None.
        """

        dp = self.decision_points.get(decision_point)
        if dp and dp.roster:
            return list(dp.roster)
        return None

    def rationale_for(self, decision_point: str) -> str:
        """Return the configured routing rationale for a decision point, or ''."""

        dp = self.decision_points.get(decision_point)
        return dp.rationale if dp else ""

    def actions_for_point(self, decision_point: str) -> List["Action"]:
        """Return actions whose ``eligible_points`` include this decision point.

        Returns an empty list when no action declares eligibility for the point,
        letting the recommender fall back to its built-in eligibility map.
        """

        return [a for a in self.actions if decision_point in (a.eligible_points or [])]

    def decision_point_for_signal(self, signal_key: str) -> Optional[str]:
        """Return the first decision point whose triggers include this signal."""

        for dp_key, dp in self.decision_points.items():
            if signal_key in dp.trigger_signals:
                return dp_key
        return None

    def playbooks_for(self, decision_point: str) -> List[Playbook]:
        """Return playbooks attached to a decision point."""

        return [pb for pb in self.playbooks if pb.decision_point == decision_point]

    def summary(self) -> Dict[str, Any]:
        """A compact dict suitable for the /domains list endpoint."""

        return {
            "key": self.domain,
            "display_name": self.display_name or self.domain,
            "actions_count": len(self.actions),
            "decision_points_count": len(self.decision_points),
        }


# ---------------------------------------------------------------------------
# Validation surface for org-uploaded packs (the "add a domain" flow).
#
# An org pastes YAML that becomes a brand new domain. Before it is stored or run
# we validate it strictly against the schema and return human readable errors,
# never a stack trace. ``validate_pack`` is the single entry point used by the
# domains API and the loader: it raises ``PackValidationError`` (carrying a flat
# list of messages) on any problem, and otherwise returns a parsed DomainPack.
# Parsing is data only (the caller does ``yaml.safe_load`` first); no code is
# ever executed.
# ---------------------------------------------------------------------------

# A domain key must be a safe slug so it is usable in URLs, filenames, and as a
# stable storage key. This also blocks path traversal and surprise characters.
_DOMAIN_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


class PackValidationError(ValueError):
    """Raised when an uploaded pack fails validation. Carries flat messages."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors) or "invalid domain pack")


def _format_pydantic_errors(exc: ValidationError) -> List[str]:
    """Flatten a pydantic ValidationError into readable ``field: message`` lines."""

    messages: List[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
        messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
    return messages


def validate_pack(raw: Any) -> DomainPack:
    """Validate a raw mapping into a DomainPack or raise PackValidationError.

    ``raw`` is the result of ``yaml.safe_load`` (data, never code). Returns a
    fully parsed pack on success. Raises ``PackValidationError`` with one or more
    human readable messages on any structural or schema problem.
    """

    if not isinstance(raw, Mapping):
        raise PackValidationError(
            ["The pack must be a YAML mapping of fields (got "
             f"{type(raw).__name__})."]
        )

    data: Dict[str, Any] = dict(raw)

    errors: List[str] = []
    domain = data.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        errors.append("domain: a non-empty domain key is required.")
    elif not _DOMAIN_KEY_RE.match(domain.strip()):
        errors.append(
            "domain: must be a lowercase slug (letters, digits, underscores), "
            "2 to 49 characters, starting with a letter (for example "
            "'field_service')."
        )
    else:
        data["domain"] = domain.strip()

    # A usable pack needs at least one decision point and one action, otherwise a
    # run on it has nothing to classify or recommend.
    if not data.get("decision_points"):
        errors.append("decision_points: at least one decision point is required.")
    if not data.get("actions"):
        errors.append("actions: at least one action is required.")

    if errors:
        raise PackValidationError(errors)

    try:
        return DomainPack.model_validate(data)
    except ValidationError as exc:
        raise PackValidationError(_format_pydantic_errors(exc)) from exc


def pack_summary(pack: DomainPack, raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """A rich summary for the validate endpoint: the headline counts of a pack.

    Reports decision points, actions, signals, KPIs, and playbooks from the
    parsed pack, plus the count of any ``policies`` declared in the raw YAML
    (policies live in an extra section, not the core schema).
    """

    policies = 0
    if raw is not None:
        section = raw.get("policies")
        if isinstance(section, list):
            policies = len(section)

    return {
        "domain": pack.domain,
        "display_name": pack.display_name or pack.domain,
        "decision_points": len(pack.decision_points),
        "actions": len(pack.actions),
        "signals": len(pack.signals),
        "kpis": len(pack.kpis),
        "playbooks": len(pack.playbooks),
        "policies": policies,
        "decision_point_labels": [
            (dp.label or key) for key, dp in pack.decision_points.items()
        ][:12],
        "action_titles": [(a.title or a.key) for a in pack.actions][:12],
    }


__all__ = [
    "Persona",
    "Signal",
    "DecisionPoint",
    "Action",
    "Playbook",
    "KPI",
    "RetrievalSource",
    "ProcessStage",
    "JourneyStage",
    "SuccessMetric",
    "DomainPack",
    "PackValidationError",
    "validate_pack",
    "pack_summary",
]
