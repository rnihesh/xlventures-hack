"""Pydantic models for a Domain Pack.

A Domain Pack is the unit of reusability for the platform: every domain specific
behavior (signals, eligible actions, decision points, KPIs, playbooks, planner
prompt) lives in a YAML file and is loaded into these models. The engine and the
specialist agents read a DomainPack as configuration, so a new vertical is a
folder of data, not a code change.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    """A classified situation that maps signals to a primary KPI and persona."""

    label: str = ""
    description: str = ""
    trigger_signals: List[str] = Field(default_factory=list)
    primary_kpi: str = ""
    default_persona: str = ""


class Action(BaseModel):
    """An eligible play the recommender may propose."""

    key: str
    title: str = ""
    description: str = ""
    eligibility: str = ""


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


class DomainPack(BaseModel):
    """A fully parsed, validated domain configuration."""

    model_config = {"extra": "allow"}

    domain: str
    display_name: str = ""
    personas: List[Persona] = Field(default_factory=list)
    signals: List[Signal] = Field(default_factory=list)
    decision_points: Dict[str, DecisionPoint] = Field(default_factory=dict)
    actions: List[Action] = Field(default_factory=list)
    playbooks: List[Playbook] = Field(default_factory=list)
    kpis: List[KPI] = Field(default_factory=list)
    retrieval_sources: List[RetrievalSource] = Field(default_factory=list)
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
