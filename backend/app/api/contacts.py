"""Contacts API.

Org-scoped CRUD over the people an org reaches out to. A contact is a ``name``,
an ``email``, an optional linked ``account_id``, and a free-text ``role``. These
back the email recipient picker (Execute panel and chat) so outreach can target
a saved person by name instead of retyping an address.

Every endpoint resolves the caller's org via ``current_org`` and delegates to the
contacts repository, which is database-backed when a pool is configured and
process-local in-memory otherwise (so the offline demo and tests round-trip).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.api._org import current_org
from app.repositories import contacts as contacts_repo

router = APIRouter(tags=["contacts"])


class ContactIn(BaseModel):
    """Payload to create a contact in the caller's org."""

    name: str = Field(description="Person's display name.")
    email: EmailStr = Field(description="Email address to reach the contact.")
    account_id: Optional[str] = Field(
        default=None, description="Optional account this contact belongs to."
    )
    role: Optional[str] = Field(
        default=None, description="Free-text role, e.g. 'Economic buyer'."
    )


class ContactUpdate(BaseModel):
    """Partial update for an existing contact (only set fields are applied)."""

    name: Optional[str] = None
    email: Optional[EmailStr] = None
    account_id: Optional[str] = None
    role: Optional[str] = None


@router.get("/contacts")
async def list_contacts(org_id: str = Depends(current_org)) -> List[Dict[str, Any]]:
    """Return every contact for the caller's org, most recent first."""

    return await contacts_repo.list_for_org(org_id)


@router.post("/contacts", status_code=201)
async def create_contact(
    body: ContactIn, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Create a contact in the caller's org."""

    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="name must not be empty")
    return await contacts_repo.upsert(
        org_id,
        name=body.name.strip(),
        email=str(body.email),
        account_id=body.account_id,
        role=body.role,
    )


@router.put("/contacts/{contact_id}")
async def update_contact(
    contact_id: str,
    body: ContactUpdate,
    org_id: str = Depends(current_org),
) -> Dict[str, Any]:
    """Update fields on an existing contact in the caller's org."""

    existing = await contacts_repo.get(org_id, contact_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="contact not found")

    fields = body.model_dump(exclude_unset=True)
    merged = dict(existing)
    for key, value in fields.items():
        merged[key] = str(value) if key == "email" and value is not None else value

    return await contacts_repo.upsert(
        org_id,
        name=merged.get("name") or existing["name"],
        email=merged.get("email") or existing["email"],
        account_id=merged.get("account_id"),
        role=merged.get("role"),
        contact_id=contact_id,
    )


@router.delete("/contacts/{contact_id}")
async def delete_contact(
    contact_id: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Remove a contact from the caller's org."""

    removed = await contacts_repo.delete(org_id, contact_id)
    if not removed:
        raise HTTPException(status_code=404, detail="contact not found")
    return {"deleted": contact_id}


@router.get("/accounts/{account_id}/contacts")
async def list_account_contacts(
    account_id: str, org_id: str = Depends(current_org)
) -> List[Dict[str, Any]]:
    """Return the org's contacts linked to a single account."""

    return await contacts_repo.list_for_account(org_id, account_id)
