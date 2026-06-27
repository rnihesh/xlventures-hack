"""Domains API: base packs plus the org's uploaded packs (extensibility flow).

This is the surface behind "add a new domain in 60 seconds". It proves the
engine is an extensible framework for new agents and business use cases: an org
pastes a domain pack YAML, it is validated against the pack schema, stored as an
org pack, appears in the domain list, and a decision can be run on it right away.

Endpoints:
  GET    /domains                 base packs + this org's uploaded packs (merged)
  GET    /domains/{domain_key}    the full parsed pack (org pack or base)
  POST   /domains/validate        parse + validate YAML, return {ok, errors, summary}
  POST   /domains                 validate then store as an org pack
  DELETE /domains/{domain}        remove one of this org's uploaded packs

Everything that mutates is org scoped via the ``nba_session`` cookie, and YAML is
only ever ``safe_load``ed and validated with pydantic, never executed.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api._org import current_org
from app.packs import loader as pack_loader
from app.packs.loader import list_packs, load_pack, reset_pack_org, set_pack_org
from app.packs.schema import PackValidationError, pack_summary, validate_pack
from app.repositories import org_packs as org_packs_repo

router = APIRouter(tags=["domains"])


class PackYaml(BaseModel):
    """The raw YAML body for validate and save."""

    yaml: str


def _org_summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Build a list summary for one uploaded org pack row."""

    parsed = rec.get("parsed") or {}
    decision_points = parsed.get("decision_points") or {}
    actions = parsed.get("actions") or []
    return {
        "key": rec.get("domain"),
        "display_name": rec.get("name") or parsed.get("display_name") or rec.get("domain"),
        "actions_count": len(actions),
        "decision_points_count": len(decision_points),
        "source": "org",
        "editable": True,
        "created_at": rec.get("created_at"),
    }


@router.get("/domains")
async def get_domains(org_id: str = Depends(current_org)) -> List[Dict[str, Any]]:
    """Return base packs merged with this org's uploaded packs, flagship first.

    Org packs are scoped to the caller, so one org never sees another's uploads.
    An org pack with the same key as a base pack shadows it (the org sees its own
    version). Each entry carries ``source`` ("base" or "org") and ``editable`` so
    the UI can offer delete only on uploaded packs.
    """

    base = list_packs()
    for item in base:
        item.setdefault("source", "base")
        item.setdefault("editable", False)

    org_rows = await org_packs_repo.list_for_org(org_id)
    org_summaries = {rec["domain"]: _org_summary(rec) for rec in org_rows}

    merged: Dict[str, Dict[str, Any]] = {}
    for item in base:
        merged[item.get("key")] = item
    for key, summary in org_summaries.items():
        merged[key] = summary  # org pack wins on key collision.

    packs = list(merged.values())
    # Customer Success is the flagship domain, so it leads the list; uploaded
    # packs sort after base packs, then alphabetically by key.
    packs.sort(
        key=lambda p: (
            p.get("key") != "customer_success",
            p.get("source") == "org",
            p.get("key") or "",
        )
    )
    return packs


@router.post("/domains/validate")
async def validate_domain(body: PackYaml) -> Dict[str, Any]:
    """Validate raw YAML against the pack schema without storing it.

    Returns ``{ok: true, summary}`` for a valid pack, or ``{ok: false, errors}``
    with human readable messages otherwise. Never raises on a bad pack: the UI
    renders the errors inline.
    """

    try:
        raw = org_packs_repo._parse_yaml(body.yaml)
        pack = validate_pack(raw)
    except PackValidationError as exc:
        return {"ok": False, "errors": exc.errors, "summary": None}

    return {"ok": True, "errors": [], "summary": pack_summary(pack, raw)}


@router.post("/domains", status_code=201)
async def create_domain(
    body: PackYaml, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Validate and store an uploaded pack as this org's domain.

    On success the pack is queryable in GET /domains and a run can target it
    immediately. On a validation failure responds 422 with the error messages.
    """

    try:
        rec = await org_packs_repo.upsert(org_id, body.yaml)
    except PackValidationError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc

    parsed = rec.get("parsed") or {}
    return {
        "ok": True,
        "domain": rec["domain"],
        "summary": _org_summary(rec),
        "created_at": rec.get("created_at"),
        "display_name": parsed.get("display_name") or rec.get("name"),
    }


@router.delete("/domains/{domain_key}")
async def delete_domain(
    domain_key: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Delete one of this org's uploaded packs (base packs cannot be deleted)."""

    removed = await org_packs_repo.delete(org_id, domain_key)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"no uploaded pack to delete for domain: {domain_key}",
        )
    return {"ok": True, "domain": domain_key}


@router.get("/domains/{domain_key}")
async def get_domain(
    domain_key: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Return the full parsed pack for one domain (the org's pack or the base).

    Binds the org so an uploaded pack (which is not on disk) resolves; ensures
    the loader registry is hydrated from storage first for a fresh process.
    """

    await org_packs_repo.hydrate_loader(org_id)
    token = set_pack_org(org_id)
    try:
        uploaded = pack_loader.org_pack(org_id, domain_key)
        if uploaded is not None:
            return uploaded.model_dump()
        if not pack_loader._disk_pack_exists(domain_key):
            raise HTTPException(
                status_code=404, detail=f"domain not found: {domain_key}"
            )
        return load_pack(domain_key).model_dump()
    finally:
        reset_pack_org(token)
