"""Configurable workflows and business rules API.

Lets each org tailor a domain pack's policy rules and action catalog from the
UI without forking the base pack. The base pack ships in
``domain_packs/<domain>.yaml`` and stays intact; an org's edits are persisted as
an additive override and merged back on read, so the policy engine and planner
read the *effective* pack for the current org.

* ``GET /rules/{domain}``  -> the effective merged policies + actions for the org.
* ``PUT /rules/{domain}``  -> save the org's override ``{policies?, actions?}``.

Every endpoint is behind the user session cookie (``Depends(current_org)``) and
scoped to the caller's org. Everything is offline-safe: with no database the
overrides fall back to an in-memory store and the merge still round-trips.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api._org import current_org
from app.packs.loader import effective_rules, load_pack
from app.repositories import pack_overrides as overrides_repo

router = APIRouter(prefix="/rules", tags=["rules"])
logger = logging.getLogger("app.api.rules")


class RulesIn(BaseModel):
    """Body for ``PUT /rules/{domain}``: the org's override for this domain.

    Either or both lists may be sent. When a list is present it defines the
    effective set for that section (policies or actions); when omitted, the base
    pack's section is left untouched. This lets the editor add, edit, and remove
    entries by sending the full desired list it derived from the effective pack.
    """

    policies: Optional[List[Dict[str, Any]]] = None
    actions: Optional[List[Dict[str, Any]]] = None


def _override_payload(body: RulesIn) -> Dict[str, Any]:
    """Build the stored override blob, including only the sections provided."""

    payload: Dict[str, Any] = {}
    if body.policies is not None:
        payload["policies"] = body.policies
    if body.actions is not None:
        payload["actions"] = body.actions
    return payload


async def _effective(org_id: str, domain: str) -> Dict[str, Any]:
    """Compute the effective merged rules view for an org and domain."""

    overrides = await overrides_repo.get_overrides(org_id, domain)
    merged = effective_rules(domain, overrides)
    pack = load_pack(domain)
    return {
        "domain": domain,
        "display_name": pack.display_name or domain,
        "policies": merged["policies"],
        "actions": merged["actions"],
        "has_override": bool(overrides),
    }


@router.get("/{domain}")
async def get_rules(
    domain: str,
    org_id: str = Depends(current_org),
) -> Dict[str, Any]:
    """Return the effective policy rules and action catalog for the org.

    The result merges the base domain pack with any saved org override, so the
    editor shows exactly what the policy engine and planner will apply.
    """

    return await _effective(org_id, domain)


@router.put("/{domain}")
async def save_rules(
    domain: str,
    body: RulesIn,
    org_id: str = Depends(current_org),
) -> Dict[str, Any]:
    """Persist the org's override for a domain and return the new effective view.

    Sending an empty body (no ``policies`` and no ``actions``) clears the
    override and reverts the org to the base pack.
    """

    payload = _override_payload(body)
    if payload:
        await overrides_repo.upsert(org_id, domain, payload)
    else:
        await overrides_repo.delete(org_id, domain)
    return await _effective(org_id, domain)
