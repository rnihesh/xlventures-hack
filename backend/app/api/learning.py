"""Learning loop API.

``GET /learning`` is the evidence surface for the "memory + measurable learning"
story. Every number it returns is computed from REAL episodes recorded by the
system (live runs plus human decisions through ``memory.record_outcome``):

  * ``accepted_rate`` : approved-or-edited over total decided episodes.
  * ``trend``         : the cumulative acceptance rate after each decision, in
    chronological order, so the UI can plot acceptance over episode order from
    real data instead of a synthetic curve.
  * ``episodes``      : recent decision episodes with their human outcomes.
  * ``before_after``  : projected NRR across the earliest decided episodes versus
    the most recent ones, computed only from outcomes that carry a measured
    ``nrr_projected`` metric. It is a clearly-labeled projection, not an actual.

The loop starts EMPTY. With zero episodes the endpoint returns a clean,
honest payload (zeros, empty lists, ``has_data: false``) and never invents a
before/after history. Run ``make gen-runs`` (or approve/reject in the UI) to
populate it from real outcomes.

``POST /learning/distill`` re-runs distillation on demand so a presenter can
trigger the improvement live, and ``POST /learning/outcome`` lets the UI write
an outcome back into memory to move the metric in real time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api._org import DEMO_ORG, current_org
from app.memory.distill import run_distillation
from app.memory.store import get_memory
from app.memory.types import ACCEPTED_LIKE

router = APIRouter(tags=["learning"])


def _for_org(episodes: List[Any], org_id: str) -> List[Any]:
    """Episodes owned by ``org_id``.

    Seeded day-zero episodes carry no ``org_id``; they belong to the Demo org,
    so an unscoped episode is treated as the demo tenant's history. Every other
    org sees only the episodes it produced.
    """
    return [ep for ep in episodes if (getattr(ep, "org_id", None) or DEMO_ORG) == org_id]


def _owned_episode(memory: Any, episode_id: str, org_id: str) -> Optional[Any]:
    """Resolve ``episode_id`` only if it belongs to ``org_id``, else ``None``.

    An episode with no ``org_id`` is owned by the Demo org (it is seeded day-zero
    history), mirroring ``_for_org``. Returning ``None`` for a missing OR a
    non-owned id lets the caller answer 404 uniformly, so a caller cannot use the
    response to tell another tenant's real episode id apart from a random one.
    """
    episode = memory.get_episode(episode_id)
    if episode is None:
        return None
    owner = getattr(episode, "org_id", None) or DEMO_ORG
    return episode if owner == org_id else None


_KPI = "Net Revenue Retention (projected %)"

_EMPTY_NOTE = (
    "No runs yet. Run 'make gen-runs' or approve/reject recommendations to start "
    "the learning loop; the acceptance trend and projected NRR fill from real "
    "outcomes."
)


def _decided(episodes: List[Any]) -> List[Any]:
    """Decided episodes (outcome present and not pending), oldest first."""
    out = [
        ep
        for ep in episodes
        if ep.outcome is not None and ep.outcome.decision != "pending"
    ]
    out.sort(key=lambda e: getattr(e, "created_at", "") or "")
    return out


def _mean(values: List[float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _counts(decided: List[Any]) -> Dict[str, int]:
    """Tally decided outcomes by canonical verb."""
    tally = {"accepted": 0, "edited": 0, "rejected": 0}
    for ep in decided:
        verb = ep.outcome.decision
        if verb in tally:
            tally[verb] += 1
    accepted_like = tally["accepted"] + tally["edited"]
    return {
        "approved": tally["accepted"],
        "edited": tally["edited"],
        "rejected": tally["rejected"],
        "accepted": accepted_like,
        "decided": len(decided),
    }


def _trend(decided: List[Any]) -> List[Dict[str, Any]]:
    """Cumulative acceptance rate after each decision, in chronological order.

    This is the real series the learning UI plots: it shows whether the team
    accepts more of the system's recommendations as outcomes accrue, computed
    purely from recorded decisions (no synthetic curve).
    """
    series: List[Dict[str, Any]] = []
    running = 0
    for i, ep in enumerate(decided, start=1):
        is_accepted = ep.outcome.decision in ACCEPTED_LIKE
        running += 1 if is_accepted else 0
        series.append(
            {
                "index": i,
                "account_id": ep.account_id,
                "decision": ep.outcome.decision,
                "accepted": is_accepted,
                "rate": round(running / i, 3),
            }
        )
    return series


def _before_after(decided: List[Any]) -> Dict[str, Any]:
    """Projected-NRR delta across the earliest versus most recent decisions.

    Uses only outcomes that recorded a measured ``nrr_projected`` metric. With
    fewer than two such outcomes it returns an honest empty state rather than a
    fabricated number. The values are a labeled projection, never an actual.
    """
    sample = [
        ep
        for ep in decided
        if isinstance(ep.outcome.metrics.get("nrr_projected"), (int, float))
    ]
    if len(sample) < 2:
        return {
            "kpi": _KPI,
            "before": 0.0,
            "after": 0.0,
            "note": _EMPTY_NOTE,
            "has_data": False,
            "projected": True,
        }

    mid = max(1, len(sample) // 2)
    early = [float(e.outcome.metrics["nrr_projected"]) for e in sample[:mid]]
    recent = [float(e.outcome.metrics["nrr_projected"]) for e in sample[mid:]]
    before = _mean(early)
    after = _mean(recent)
    delta = round(after - before, 1)
    note = (
        f"Projected from {len(sample)} real outcomes: projected NRR moved "
        f"{delta:+.1f} points from the earliest decisions to the most recent "
        "(model projection, not an actual)."
    )
    return {
        "kpi": _KPI,
        "before": before,
        "after": after,
        "note": note,
        "has_data": True,
        "projected": True,
    }


def _empty_payload(memory: Any) -> Dict[str, Any]:
    return {
        "episodes": [],
        "accepted_rate": 0.0,
        "decided": 0,
        "accepted": 0,
        "approved": 0,
        "edited": 0,
        "rejected": 0,
        "total": 0,
        "trend": [],
        "before_after": {
            "kpi": _KPI,
            "before": 0.0,
            "after": 0.0,
            "note": _EMPTY_NOTE,
            "has_data": False,
            "projected": True,
        },
        "has_data": False,
        "preferences_version": memory._pref_version,
    }


@router.get("/learning")
async def get_learning(org_id: str = Depends(current_org)) -> Dict[str, Any]:
    """Return the org's episodes, acceptance rate, acceptance trend, and a delta."""

    memory = get_memory()
    # Hydrate persisted episodes from Postgres (no-op offline) so the learning
    # surface reflects real outcomes written by live runs and gen_runs.
    await memory._ensure_db()
    episodes = _for_org(memory.all_episodes(), org_id)

    if not episodes:
        return _empty_payload(memory)

    decided = _decided(episodes)
    counts = _counts(decided)
    accepted_rate = (
        round(counts["accepted"] / counts["decided"], 3) if counts["decided"] else 0.0
    )

    # Most recent first for the timeline UI.
    public = [ep.public() for ep in episodes]
    public.sort(key=lambda e: e["created_at"], reverse=True)

    return {
        "episodes": public,
        "accepted_rate": accepted_rate,
        "decided": counts["decided"],
        "accepted": counts["accepted"],
        "approved": counts["approved"],
        "edited": counts["edited"],
        "rejected": counts["rejected"],
        "total": len(episodes),
        "trend": _trend(decided),
        "before_after": _before_after(decided),
        "has_data": counts["decided"] > 0,
        "preferences_version": memory._pref_version,
    }


@router.post("/learning/distill")
async def trigger_distillation() -> Dict[str, Any]:
    """Re-run distillation on demand and return the updated summary."""
    memory = get_memory()
    await memory._ensure_db()
    summary = run_distillation(memory)
    return {"status": "distilled", "summary": summary}


class OutcomeIn(BaseModel):
    episode_id: str
    decision: str = Field(
        ..., description="approve | reject | edit (or accepted/rejected/edited)"
    )
    reason: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None


@router.post("/learning/outcome")
async def record_learning_outcome(
    body: OutcomeIn, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Write an outcome back into memory so the learning metric moves live.

    The ``episode_id`` is an opaque, caller-supplied id, so we resolve it and
    confirm it belongs to the caller's org before recording. A missing or
    other-org episode returns 404 (not 403) so the endpoint cannot be used to
    enumerate which episode ids exist for other tenants, and no outcome is
    written against memory the caller does not own.
    """
    memory = get_memory()
    await memory._ensure_db()
    if _owned_episode(memory, body.episode_id, org_id) is None:
        raise HTTPException(status_code=404, detail="episode not found")
    await memory.record_outcome(
        body.episode_id, body.decision, body.reason, body.metrics
    )
    decided = _decided(_for_org(memory.all_episodes(), org_id))
    counts = _counts(decided)
    return {
        "status": "recorded",
        "accepted_rate": (
            round(counts["accepted"] / counts["decided"], 3) if counts["decided"] else 0.0
        ),
        "preferences_version": memory._pref_version,
    }
