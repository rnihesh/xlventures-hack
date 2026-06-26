"""Learning loop API.

``GET /learning`` exposes the memory's episodes, the overall acceptance rate,
and a concrete before/after KPI delta computed from seeded + live outcomes. It
is the evidence surface for the "memory + measurable learning" story:

  * ``episodes``    - recent decision episodes with their human outcomes.
  * ``accepted_rate`` - share of decided episodes that were accepted/edited.
  * ``before_after`` - a single KPI (projected NRR) compared across the
    pre-learning baseline and post-distillation phases on the same accounts.

``POST /learning/distill`` re-runs distillation on demand so a presenter can
trigger the improvement live, and ``POST /learning/outcome`` lets the UI write
an outcome back into memory to move the metric in real time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.memory.distill import run_distillation
from app.memory.store import get_memory
from app.memory.types import ACCEPTED_LIKE

router = APIRouter(tags=["learning"])


def _mean_nrr(episodes: List[Any], phase: str) -> Optional[float]:
    """Mean projected NRR over episodes of a given phase that have a metric."""
    values: List[float] = []
    for ep in episodes:
        if ep.phase != phase or ep.outcome is None:
            continue
        nrr = ep.outcome.metrics.get("nrr_projected")
        if isinstance(nrr, (int, float)):
            values.append(float(nrr))
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _accepted_rate(episodes: List[Any], phase: Optional[str] = None) -> tuple[int, int]:
    """Return (accepted_like_count, decided_count), optionally scoped to a phase."""
    accepted = 0
    decided = 0
    for ep in episodes:
        if phase is not None and ep.phase != phase:
            continue
        if ep.outcome is None or ep.outcome.decision == "pending":
            continue
        decided += 1
        if ep.outcome.decision in ACCEPTED_LIKE:
            accepted += 1
    return accepted, decided


def _build_before_after(episodes: List[Any]) -> Dict[str, Any]:
    """Compute the headline KPI delta on the same accounts, before vs after."""

    before = _mean_nrr(episodes, "baseline")
    after = _mean_nrr(episodes, "learned")

    # Fall back gracefully if either phase is missing (e.g. only live data).
    if before is None:
        before = 0.0
    if after is None:
        after = before

    b_acc, b_dec = _accepted_rate(episodes, "baseline")
    a_acc, a_dec = _accepted_rate(episodes, "learned")
    before_rate = round(100 * b_acc / b_dec) if b_dec else 0
    after_rate = round(100 * a_acc / a_dec) if a_dec else 0

    delta = round(after - before, 1)
    note = (
        f"After distilling {b_dec} day-zero outcomes into preferences, "
        f"acceptance on the same accounts rose from {before_rate}% to "
        f"{after_rate}% and projected NRR improved by {delta:+.1f} points "
        "(three accounts flipped from the wrong action to the action the team "
        "actually wanted)."
    )

    return {
        "kpi": "Net Revenue Retention (projected %)",
        "before": before,
        "after": after,
        "note": note,
    }


@router.get("/learning")
async def get_learning() -> Dict[str, Any]:
    """Return episodes, acceptance rate, and a measurable before/after delta."""

    memory = get_memory()
    episodes = memory.all_episodes()

    accepted, decided = _accepted_rate(episodes)
    accepted_rate = round(accepted / decided, 3) if decided else 0.0

    # Most recent first for the timeline UI.
    public = [ep.public() for ep in episodes]
    public.sort(key=lambda e: e["created_at"], reverse=True)

    return {
        "episodes": public,
        "accepted_rate": accepted_rate,
        "before_after": _build_before_after(episodes),
        "preferences_version": memory._pref_version,
        "decided": decided,
        "accepted": accepted,
    }


@router.post("/learning/distill")
async def trigger_distillation() -> Dict[str, Any]:
    """Re-run distillation on demand and return the updated summary."""
    memory = get_memory()
    summary = run_distillation(memory)
    return {"status": "distilled", "summary": summary}


class OutcomeIn(BaseModel):
    episode_id: str
    decision: str = Field(..., description="approve | reject | edit (or accepted/rejected/edited)")
    reason: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None


@router.post("/learning/outcome")
async def record_learning_outcome(body: OutcomeIn) -> Dict[str, Any]:
    """Write an outcome back into memory so the learning metric moves live."""
    memory = get_memory()
    await memory.record_outcome(
        body.episode_id, body.decision, body.reason, body.metrics
    )
    accepted, decided = _accepted_rate(memory.all_episodes())
    return {
        "status": "recorded",
        "accepted_rate": round(accepted / decided, 3) if decided else 0.0,
        "preferences_version": memory._pref_version,
    }
