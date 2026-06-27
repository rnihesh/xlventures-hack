"""Workflow Studio API: view and edit the agent orchestration per domain.

The planner's pipeline topology is fixed, but WHICH specialists run at each
decision point (the roster) is configuration. This endpoint exposes the graph
(stages, always-on nodes, selectable specialists, and each decision point's
roster) and lets an org pin a custom roster per decision point. The override is
stored in the same per-org ``pack_overrides`` blob the Rules editor uses (under
a ``rosters`` key) and is honored by the planner at run time via
``set_roster_overrides``. Org-scoped; one tenant never sees another's edits.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api._org import current_org
from app.packs.loader import load_pack, reset_pack_org, set_pack_org
from app.repositories import pack_overrides as overrides_repo

router = APIRouter(prefix="/workflow", tags=["workflow"])


class WorkflowIn(BaseModel):
    # {decision_point_key: [capability, ...]}. An empty/omitted map clears the
    # roster override and reverts to the pack's configured rosters.
    rosters: Dict[str, List[str]] = Field(default_factory=dict)


def _specialists() -> List[Dict[str, Any]]:
    """The selectable specialist roster the planner draws from, in run order."""
    from app.graph.planner import _ALWAYS_ON, _PIPELINE, _SEQUENCE
    from app.packs.registry import AGENTS

    out: List[Dict[str, Any]] = []
    for cap in _SEQUENCE:
        if cap in _PIPELINE and AGENTS.has(cap):
            card = AGENTS.find(cap)
            out.append(
                {
                    "capability": cap,
                    "description": card.description if card else "",
                    "always_on": cap in _ALWAYS_ON,
                }
            )
    return out


def _pack_for(org_id: str, domain: str):
    token = set_pack_org(org_id)
    try:
        return load_pack(domain)
    finally:
        reset_pack_org(token)


async def _view(org_id: str, domain: str) -> Dict[str, Any]:
    from app.graph.planner import _ALWAYS_ON, _SEQUENCE, _deterministic_roster

    pack = _pack_for(org_id, domain)
    blob = await overrides_repo.get_overrides(org_id, domain)
    roster_ovr = (blob or {}).get("rosters") or {}

    decision_points: List[Dict[str, Any]] = []
    for key, dp in (pack.decision_points or {}).items():
        base_roster, base_rationale = _deterministic_roster(pack, key)
        override = roster_ovr.get(key)
        decision_points.append(
            {
                "key": key,
                "label": getattr(dp, "label", key),
                "signals": list(
                    getattr(dp, "signals", None) or getattr(dp, "signal_types", None) or []
                ),
                "base_roster": base_roster,
                "rationale": base_rationale,
                "roster": list(override) if override else base_roster,
                "overridden": bool(override),
            }
        )

    return {
        "domain": domain,
        "domain_name": getattr(pack, "name", domain),
        "sequence": list(_SEQUENCE),
        "always_on": sorted(_ALWAYS_ON),
        "specialists": _specialists(),
        "decision_points": decision_points,
        "has_override": bool(roster_ovr),
    }


@router.get("/{domain}")
async def get_workflow(
    domain: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Return the orchestration graph and each decision point's effective roster."""
    return await _view(org_id, domain)


@router.put("/{domain}")
async def put_workflow(
    domain: str, body: WorkflowIn, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Save the org's per-decision-point roster overrides (merged onto rules)."""
    blob: Dict[str, Any] = await overrides_repo.get_overrides(org_id, domain) or {}
    cleaned = {
        key: [str(c) for c in caps]
        for key, caps in (body.rosters or {}).items()
        if caps
    }
    if cleaned:
        blob["rosters"] = cleaned
    else:
        blob.pop("rosters", None)

    if blob:
        await overrides_repo.upsert(org_id, domain, blob)
    else:
        await overrides_repo.delete(org_id, domain)
    return await _view(org_id, domain)
