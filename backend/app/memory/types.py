"""Pydantic models for the memory + learning loop.

These models are intentionally permissive (extra fields ignored, sensible
defaults) so seed data, live runs, and distilled preferences all serialize
cleanly through the in-memory store and the learning API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


def now_iso() -> str:
    """Return the current UTC time as an ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


# Normalization map: callers may pass HITL verbs (approve/reject/edit) or the
# canonical outcome verbs. We always store the canonical form.
DECISION_NORMALIZE: Dict[str, str] = {
    "approve": "accepted",
    "approved": "accepted",
    "accept": "accepted",
    "accepted": "accepted",
    "edit": "edited",
    "edited": "edited",
    "reject": "rejected",
    "rejected": "rejected",
    "dismiss": "rejected",
    "dismissed": "rejected",
    "pending": "pending",
}

# Decisions that mean the recommended (or edited) action was actually taken.
ACCEPTED_LIKE = {"accepted", "edited"}


def normalize_decision(decision: str) -> str:
    """Map any inbound decision verb to a canonical outcome verb."""
    return DECISION_NORMALIZE.get((decision or "").strip().lower(), "pending")


class Outcome(BaseModel):
    """The recorded result of a human reviewing a recommendation."""

    decision: str = "pending"  # accepted | edited | rejected | pending
    reason: Optional[str] = None
    # Free-form measured metrics, e.g. {"nrr_projected": 112.0, "arr_at_risk": 0}.
    metrics: Dict[str, Any] = Field(default_factory=dict)
    recorded_at: str = Field(default_factory=now_iso)

    @field_validator("decision", mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> str:
        """Accept HITL verbs (approve/reject/edit) or canonical verbs alike."""
        return normalize_decision(value if isinstance(value, str) else "pending")

    @property
    def accepted_like(self) -> bool:
        """True when the action was taken (accepted or accepted-after-edit)."""
        return self.decision in ACCEPTED_LIKE


class Episode(BaseModel):
    """A single decision episode stored against an account.

    ``phase`` lets the learning loop separate the pre-learning baseline from
    post-distillation behavior so a before/after delta can be computed on the
    same accounts:

      * ``baseline`` - day-zero recommendations made before any learning.
      * ``learned``  - recommendations made after distillation was applied.
      * ``live``     - episodes produced by real runs at demo time.
    """

    id: str
    account_id: str
    domain: str
    # Owning org for multi-tenant scoping. ``None`` means the Demo org, which
    # owns all seeded day-zero episodes, so the learning loop treats unscoped
    # episodes as the demo tenant's history.
    org_id: Optional[str] = None
    situation: str
    action_key: str
    recommendation: Dict[str, Any] = Field(default_factory=dict)
    phase: str = "live"
    # When the system was wrong, the action the human actually wanted. This is
    # what distillation turns into a procedural "prefer X over Y" rule.
    preferred_action_key: Optional[str] = None
    outcome: Optional[Outcome] = None
    created_at: str = Field(default_factory=now_iso)

    def public(self) -> Dict[str, Any]:
        """A flat, JSON-friendly projection for the learning API."""
        decision = self.outcome.decision if self.outcome else "pending"
        metrics = self.outcome.metrics if self.outcome else {}
        reason = self.outcome.reason if self.outcome else None
        title = (self.recommendation or {}).get("action", {}).get("title")
        return {
            "id": self.id,
            "account_id": self.account_id,
            "domain": self.domain,
            "situation": self.situation,
            "action_key": self.action_key,
            "action_title": title,
            "preferred_action_key": self.preferred_action_key,
            "phase": self.phase,
            "decision": decision,
            "reason": reason,
            "metrics": metrics,
            "created_at": self.created_at,
        }


class Preference(BaseModel):
    """A learned preference for one action within a domain.

    ``weight`` is a signed score in roughly [-1, 1]: positive means humans tend
    to accept this action, negative means they tend to reject it. ``rules`` are
    human-readable procedural guides distilled from rejected episodes, and
    ``few_shot`` holds accepted situation -> action exemplars that can be fed
    back to the recommender as in-context examples.
    """

    domain: str
    action_key: str
    weight: float = 0.0
    accept_count: int = 0
    reject_count: int = 0
    rules: List[str] = Field(default_factory=list)
    few_shot: List[Dict[str, Any]] = Field(default_factory=list)
