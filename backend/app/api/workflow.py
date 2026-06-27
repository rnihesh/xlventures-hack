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

import logging

from app.api._org import current_org
from app.packs.loader import load_pack, reset_pack_org, set_pack_org
from app.repositories import pack_overrides as overrides_repo

logger = logging.getLogger("app.api.workflow")

router = APIRouter(prefix="/workflow", tags=["workflow"])


class WorkflowIn(BaseModel):
    # {decision_point_key: [capability, ...]}. An empty/omitted map clears the
    # roster override and reverts to the pack's configured rosters.
    rosters: Dict[str, List[str]] = Field(default_factory=dict)


# Tools the planner specialists call in-graph, mapped to their node. Augments the
# registry bindings (which only tag a few) so each node shows real tool usage.
_NODE_TOOLS: Dict[str, List[str]] = {
    "retrieval": ["hybrid_search", "search_knowledge"],
    "risk_scorer": ["kpi_simulate"],
    "play_recommender": ["recall_similar"],
    "outcome_simulator": ["kpi_simulate"],
    "drafter": ["draft_email"],
    "critic": ["evaluate_policy"],
}


def _tools_for(capability: str) -> List[str]:
    """Tools associated with a specialist (registry bindings plus the map above)."""
    from app.packs.registry import TOOLS

    tools = set(_NODE_TOOLS.get(capability, []))
    for spec in TOOLS.specs():
        if (spec.binding or {}).get("node") == capability:
            tools.add(spec.name)
    return sorted(tools)


def _specialists() -> List[Dict[str, Any]]:
    """The selectable specialist roster the planner draws from, in run order."""
    from app.graph.planner import _ALWAYS_ON, _PIPELINE, _SEQUENCE
    from app.packs.registry import AGENTS

    out: List[Dict[str, Any]] = []
    for cap in _SEQUENCE:
        if cap in _PIPELINE and AGENTS.has(cap):
            card = AGENTS.find(cap)
            pub = card.public() if card else {}
            out.append(
                {
                    "capability": cap,
                    "description": pub.get("description", ""),
                    "output_keys": pub.get("output_keys", []),
                    "cost_tier": pub.get("cost_tier", "standard"),
                    "tags": pub.get("tags", []),
                    "tools": _tools_for(cap),
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

    # Annotate each specialist with the decision points whose effective roster
    # includes it, so the UI can show "where is this used".
    specialists = _specialists()
    for spec in specialists:
        spec["used_in"] = [
            dp["key"] for dp in decision_points if spec["capability"] in dp["roster"]
        ]

    return {
        "domain": domain,
        "domain_name": getattr(pack, "name", domain),
        "sequence": list(_SEQUENCE),
        "always_on": sorted(_ALWAYS_ON),
        "specialists": specialists,
        "decision_points": decision_points,
        "has_override": bool(roster_ovr),
    }


@router.get("/{domain}")
async def get_workflow(
    domain: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Return the orchestration graph and each decision point's effective roster."""
    return await _view(org_id, domain)


class AssistantIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _selectable_caps(view: Dict[str, Any]) -> List[str]:
    return [s["capability"] for s in view["specialists"] if not s["always_on"]]


def _validate_changes(
    changes: Dict[str, Any], view: Dict[str, Any]
) -> Dict[str, List[str]]:
    """Keep only known decision points and selectable capabilities, in run order."""
    selectable = _selectable_caps(view)
    seq = view["sequence"]
    dp_keys = {dp["key"] for dp in view["decision_points"]}
    clean: Dict[str, List[str]] = {}
    for key, caps in (changes or {}).items():
        if key not in dp_keys or not isinstance(caps, list):
            continue
        chosen = {str(c) for c in caps if str(c) in selectable}
        clean[key] = [c for c in seq if c in chosen]
    return clean


async def _llm_plan(message: str, view: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ask the model to turn a free-text instruction into roster changes."""
    from app.demo import demo_mode_enabled

    if demo_mode_enabled():
        return None
    from app.config import settings
    from app.deps import get_llm

    selectable = _selectable_caps(view)
    rosters = {
        dp["key"]: [c for c in dp["roster"] if c in selectable]
        for dp in view["decision_points"]
    }
    prompt = (
        "You configure an agentic decision workflow. Output STRICT JSON only.\n"
        f"Selectable specialists (you may only use these): {selectable}\n"
        "Always-on specialists gap_analysis and critic ALWAYS run and are never listed.\n"
        f"Decision points and their current selectable roster: {rosters}\n\n"
        f'User instruction: "{message}"\n\n'
        "Return JSON: {\"changes\": {\"<decision_point>\": [\"capability\", ...]}, "
        '"reply": "<one short sentence describing what you changed>"}. '
        "Each changed decision point maps to the FULL new selectable roster (not a diff). "
        "Only include decision points you are changing. If the instruction is unclear or "
        "off-topic, return {\"changes\": {}, \"reply\": \"...\"} explaining what you need."
    )
    try:
        import json

        # Use the org's configured model (the one chat/runs use) and the async
        # path so the async usage callback does not error a sync .invoke. No
        # extra callbacks here: a config edit need not record usage.
        llm = get_llm(model=settings.openai_model, temperature=0, callbacks=[])
        resp = await llm.ainvoke(prompt)
        text = getattr(resp, "content", "") or ""
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(text[start : end + 1])
    except Exception as exc:  # noqa: BLE001 - fall back to deterministic parsing
        logger.warning("workflow assistant LLM failed, using fallback: %s", exc)
        return None


def _deterministic_plan(message: str, view: Dict[str, Any]) -> Dict[str, Any]:
    """Offline fallback: parse a few simple commands against the current rosters."""
    import re

    selectable = _selectable_caps(view)
    msg = message.lower()
    # Resolve a capability mentioned in the text (by key or a loose word match).
    def caps_in(text: str) -> List[str]:
        found = []
        for cap in selectable:
            if cap in text or cap.replace("_", " ") in text:
                found.append(cap)
        return found

    # Resolve target decision point(s) from the original message.
    targets = [dp["key"] for dp in view["decision_points"] if dp["key"] in msg or dp["label"].lower() in msg]

    # Strip decision-point names before matching COMMAND keywords so a label word
    # (e.g. "drop" in "health drop") cannot be mistaken for the "drop" command.
    kw = msg
    for dp in view["decision_points"]:
        for token in (dp["label"].lower(), dp["key"], dp["key"].replace("_", " ")):
            kw = kw.replace(token, " ")

    rosters = {dp["key"]: list(dp["roster"]) for dp in view["decision_points"]}
    seq = view["sequence"]
    changes: Dict[str, List[str]] = {}
    mentioned = caps_in(msg)
    scope = targets or [dp["key"] for dp in view["decision_points"]]
    wants_all = bool(re.search(r"\b(all|everything|every)\b", kw))

    remove_kw = bool(re.search(r"\b(remove|drop|exclude|without|disable|turn off|turn of)\b", kw))
    add_kw = bool(re.search(r"\b(add|include|enable|activate|also run)\b", kw))
    only_kw = bool(re.search(r"\bonly\b", kw))
    reset_kw = bool(re.search(r"\b(reset|default|revert|restore)\b", kw))

    if reset_kw:
        for k in scope:
            base = next(dp["base_roster"] for dp in view["decision_points"] if dp["key"] == k)
            changes[k] = [c for c in base if c in selectable]
    elif remove_kw and (mentioned or wants_all):
        rem = set(mentioned) if mentioned else set(selectable)  # "remove all" empties it
        for k in scope:
            changes[k] = [c for c in rosters[k] if c not in rem]
    elif add_kw and (mentioned or wants_all):
        add = set(mentioned) if mentioned else set(selectable)  # "add all"
        for k in scope:
            current = set(rosters[k]) | add
            changes[k] = [c for c in seq if c in current and c in selectable]
    elif only_kw and mentioned:
        for k in scope:
            changes[k] = [c for c in seq if c in set(mentioned)]
    reply = (
        "Updated the roster." if changes else
        "Tell me what to change, for example 'remove the outcome simulator from renewal risk', "
        "'add all to health drop', or 'reset all to defaults'."
    )
    return {"changes": changes, "reply": reply}


@router.post("/{domain}/assistant")
async def workflow_assistant(
    domain: str, body: AssistantIn, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Edit the workflow from a natural-language instruction (context aware).

    Reads the org's current effective workflow, asks the model (or an offline
    parser) for the new rosters, validates them against the selectable
    specialists, persists, and returns the updated view plus a short reply.
    """
    view = await _view(org_id, domain)
    plan = await _llm_plan(body.message, view) or _deterministic_plan(body.message, view)
    changes = _validate_changes(plan.get("changes") or {}, view)
    reply = str(plan.get("reply") or "").strip() or "Done."

    if changes:
        blob: Dict[str, Any] = await overrides_repo.get_overrides(org_id, domain) or {}
        rosters = dict((blob or {}).get("rosters") or {})
        rosters.update(changes)
        # Drop entries that now equal the base roster so the override stays minimal.
        base_by_key = {dp["key"]: dp["base_roster"] for dp in view["decision_points"]}
        rosters = {k: v for k, v in rosters.items() if v != base_by_key.get(k)}
        if rosters:
            blob["rosters"] = rosters
        else:
            blob.pop("rosters", None)
        if blob:
            await overrides_repo.upsert(org_id, domain, blob)
        else:
            await overrides_repo.delete(org_id, domain)

    return {"reply": reply, "changes": changes, "view": await _view(org_id, domain)}


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
