"""Domains API.

Lists the available domain packs so the UI can prove the engine is reusable: a
new vertical is a YAML file in ``domain_packs/``, surfaced here with its action
and decision-point counts.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from app.packs.loader import list_packs, load_pack

router = APIRouter(tags=["domains"])


@router.get("/domains")
async def get_domains() -> List[Dict[str, Any]]:
    """Return a summary of every domain pack on disk."""

    return list_packs()


@router.get("/domains/{domain_key}")
async def get_domain(domain_key: str) -> Dict[str, Any]:
    """Return the full parsed pack for one domain."""

    try:
        pack = load_pack(domain_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"domain not found: {domain_key}") from exc

    return pack.model_dump()
