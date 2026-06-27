"""Agents and Tools catalog API.

Surfaces the reusable agent + tool architecture so judges (and operators) can
see the framework directly: every specialist is an ``AgentCard`` registered
under a capability, and every callable is a governance-tagged ``ToolSpec``. The
planner looks specialists up by capability at runtime and never imports their
code, so adding a capability is a registration, not a graph edit. This endpoint
just serializes those two registries.

Read-only and offline-safe: if the registry import fails for any reason the
endpoints degrade to an empty list rather than erroring, so the page still
renders. Public (no org scope), consistent with the domains catalog.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter

logger = logging.getLogger("app.api.agents")

router = APIRouter(tags=["agents"])


def _load_registries() -> Any:
    """Import the registries with their specialist registrations applied.

    Agent cards register as a side effect of importing the specialist modules
    (their ``@register_agent`` decorators run on import), so ``app.agents`` is
    imported first to populate ``AGENTS``. Returns ``(AGENTS, TOOLS)`` or
    ``(None, None)`` when the import path is unavailable (kept offline-safe).
    """

    try:
        import app.agents  # noqa: F401  (import for decorator side effects)
        from app.packs.registry import AGENTS, TOOLS

        return AGENTS, TOOLS
    except Exception:  # noqa: BLE001 - never fail the catalog on an import hiccup
        logger.exception("agent/tool registry import failed; serving empty catalog")
        return None, None


# Nodes that run in the graph on every decision but are not roster-selected
# specialists (so they are not in the AgentCard registry). Surfaced here so the
# Agents page reflects the WHOLE graph the judges watch run, not only the
# planner-gated specialists. gap_analysis is a genuine reasoning agent; the rest
# are orchestration / governance / memory nodes.
_ALWAYS_ON_NODES: List[Dict[str, Any]] = [
    {
        "capability": "planner",
        "description": "Reads the signals and account context, then selects which specialists run for this decision point.",
        "output_keys": ["plan", "capabilities"],
        "cost_tier": "strong",
        "tags": ["orchestration", "always-on"],
    },
    {
        "capability": "gap_analysis",
        "description": "Names the information still missing to decide well, and can loop back to retrieval before the recommendation is formed.",
        "output_keys": ["gaps", "missing_information"],
        "cost_tier": "standard",
        "tags": ["reasoning", "always-on"],
    },
    {
        "capability": "policy_gate",
        "description": "Checks every candidate action against the org's policy guardrails before a human ever sees it.",
        "output_keys": ["policy"],
        "cost_tier": "cheap",
        "tags": ["governance", "always-on"],
    },
    {
        "capability": "hitl_gate",
        "description": "Routes high-risk or low-confidence actions to human approval instead of auto-approving.",
        "output_keys": ["hitl"],
        "cost_tier": "cheap",
        "tags": ["governance", "always-on"],
    },
    {
        "capability": "commit",
        "description": "Writes the decision episode to memory so the learning loop improves future runs.",
        "output_keys": ["episode_id"],
        "cost_tier": "cheap",
        "tags": ["memory", "always-on"],
    },
]


@router.get("/agents")
async def get_agents() -> List[Dict[str, Any]]:
    """Return the agent registry plus always-on graph nodes as serializable cards.

    Each card exposes name (capability), description, the state ``output_keys``
    the node produces, its ``cost_tier``, and ``tags``: everything the planner
    needs to route work, minus the node callable.
    """

    agents, _ = _load_registries()
    cards = agents.public_cards() if agents is not None else []
    registered = {card.get("capability") for card in cards}
    # Append the always-on graph nodes the roster never gates, skipping any that
    # happen to also be registered specialists.
    for node in _ALWAYS_ON_NODES:
        if node["capability"] not in registered:
            cards.append(dict(node))
    # Expose ``name`` as an alias of ``capability`` so the UI can key on a
    # stable label without assuming the registry's internal field name.
    for card in cards:
        card.setdefault("name", card.get("capability"))
    return cards


@router.get("/tools")
async def get_tools() -> List[Dict[str, Any]]:
    """Return the tool registry with governance metadata.

    Each spec exposes name, description, ``side_effecting`` (does it mutate the
    world), ``risk_tier``, and the ``binding`` that resolves the implementation,
    so the policy and approval story is auditable from one place.
    """

    _, tools = _load_registries()
    if tools is None:
        return []
    return [
        {
            "name": spec.name,
            "kind": spec.kind,
            "description": spec.description,
            "side_effecting": spec.side_effecting,
            "risk_tier": spec.risk_tier,
            "binding": spec.binding,
        }
        for spec in tools.specs()
    ]
