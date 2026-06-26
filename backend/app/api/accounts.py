"""Accounts API.

Serves the triage inbox and the account 360 view, scoped to the caller's org.
Accounts live in the ``accounts`` table (one row per ``(org_id, account_id)``);
the Demo org owns the seeded corpus in ``backend/seeds/<domain>/`` (the same
data the retriever and ingest use). When no database is configured the Demo org
is served from that seed corpus so the offline path is identical to before. New
orgs start empty. Prior recommendation history is enriched from memory when the
memory slice is available. No hardcoded account list lives here.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import seed_data
from app.api._org import DEMO_ORG, current_org
from app.deps import get_pool
from app.repositories.accounts_repo import AccountsRepository

logger = logging.getLogger("app.api.accounts")

router = APIRouter(tags=["accounts"])

# Offline (no pool) store for org-scoped accounts created at runtime, keyed by
# org_id then account_id. Mirrors the accounts table so create / import-demo /
# update / delete round-trip in tests and demos with no database, while the DB
# path stays authoritative when a pool is configured.
_MEM_ACCOUNTS: Dict[str, Dict[str, Dict[str, Any]]] = {}

# Verticals served by the inbox. Each maps to a backend/seeds/<domain>/ folder.
_DOMAINS = ["customer_success", "saas_sales", "collections"]

# Risk ordering for the triage queue (most urgent first).
_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _humanize(key: str) -> str:
    """Turn a signal key like 'support_ticket_spike' into a readable label."""

    return key.replace("_", " ").strip().capitalize()


@lru_cache(maxsize=1)
def _accounts_by_id() -> Dict[str, Dict[str, Any]]:
    """Load every seeded account across domains, tagged with its domain."""

    out: Dict[str, Dict[str, Any]] = {}
    for domain in _DOMAINS:
        for acc in seed_data.load_accounts(domain):
            acc = dict(acc)
            acc.setdefault("domain", domain)
            out[acc["account_id"]] = acc
    return out


@lru_cache(maxsize=8)
def _documents_by_account(domain: str) -> Dict[str, List[Dict[str, Any]]]:
    """Group a domain's seed documents by account id."""

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for doc in seed_data.load_documents(domain):
        acc_id = doc.get("account_id")
        if acc_id:
            grouped.setdefault(acc_id, []).append(doc)
    return grouped


def _seed_accounts(domain: Optional[str]) -> List[Dict[str, Any]]:
    """Demo-org accounts from the seed corpus, optionally scoped to a domain."""

    return [
        a
        for a in _accounts_by_id().values()
        if domain is None or a.get("domain") == domain
    ]


async def _org_accounts(org_id: str, domain: Optional[str]) -> List[Dict[str, Any]]:
    """Accounts for ``org_id``, from the DB when available else the demo seed.

    A database-backed deployment reads the org's rows from the ``accounts``
    table (empty for a brand-new org). The Demo org falls back to the seed
    corpus when the table has not been seeded (or there is no database at all),
    so the offline path is unchanged.
    """

    pool = await get_pool()
    if pool is not None:
        rows = await AccountsRepository(pool).list_for_org(org_id, domain)
        if rows:
            return rows
        if org_id == DEMO_ORG:
            return _seed_accounts(domain)
        return []
    # Offline: the in-memory store holds accounts created this process, plus the
    # seed corpus for the Demo org.
    mem = list(_MEM_ACCOUNTS.get(org_id, {}).values())
    if domain is not None:
        mem = [a for a in mem if a.get("domain") == domain]
    if org_id == DEMO_ORG:
        seeded = {a["account_id"] for a in mem}
        return mem + [a for a in _seed_accounts(domain) if a["account_id"] not in seeded]
    return mem


async def _org_account(org_id: str, account_id: str) -> Optional[Dict[str, Any]]:
    """One account for ``org_id``, from the DB when available else the demo seed."""

    pool = await get_pool()
    if pool is not None:
        account = await AccountsRepository(pool).get(org_id, account_id)
        if account is not None:
            return account
        if org_id != DEMO_ORG:
            return None
        return _accounts_by_id().get(account_id)
    mem = _MEM_ACCOUNTS.get(org_id, {}).get(account_id)
    if mem is not None:
        return mem
    return _accounts_by_id().get(account_id) if org_id == DEMO_ORG else None


def _gen_account_id() -> str:
    """Return a stable, readable account id (e.g. ``ACC-9f3a2b``)."""

    return f"ACC-{uuid.uuid4().hex[:6]}"


def _slugify_signal(value: str) -> str:
    """Turn a human label into a signal key (``Support spike`` -> ``support_spike``)."""

    return "_".join(value.strip().lower().split())


def _normalize_signals(signals: Optional[List[Any]]) -> List[str]:
    """Coerce signal inputs (strings or ``{key,label}`` dicts) into signal keys."""

    keys: List[str] = []
    for item in signals or []:
        key = ""
        if isinstance(item, str):
            key = item.strip()
            if " " in key:
                key = _slugify_signal(key)
        elif isinstance(item, dict):
            raw = (item.get("key") or item.get("label") or "").strip()
            key = raw if (raw and " " not in raw) else _slugify_signal(raw)
        if key:
            keys.append(key)
    return keys


async def _persist_account(org_id: str, account: Dict[str, Any]) -> None:
    """Upsert an account into the DB when available, else the in-memory store."""

    pool = await get_pool()
    if pool is not None:
        await AccountsRepository(pool).upsert(
            org_id,
            account["account_id"],
            account.get("domain", "customer_success"),
            account,
        )
        return
    _MEM_ACCOUNTS.setdefault(org_id, {})[account["account_id"]] = account


async def _delete_account(org_id: str, account_id: str) -> bool:
    """Remove an account from the org. True when a row was removed."""

    pool = await get_pool()
    if pool is not None:
        existing = await AccountsRepository(pool).get(org_id, account_id)
        if existing is None:
            return False
        await pool.execute(
            "DELETE FROM accounts WHERE org_id = $1 AND account_id = $2",
            org_id,
            account_id,
        )
        return True
    org_mem = _MEM_ACCOUNTS.get(org_id, {})
    if account_id in org_mem:
        del org_mem[account_id]
        return True
    return False


async def _ingest_notes(
    *, text: str, account_id: str, name: str, domain: str
) -> None:
    """Best-effort: ingest account notes as retrievable evidence (offline-safe)."""

    try:
        from app.retrieval.connectors import TextImportConnector

        await TextImportConnector().ingest(
            text=text,
            source_type="note",
            title=f"{name} notes",
            account_id=account_id,
            domain=domain,
        )
    except Exception as exc:  # noqa: BLE001 - never fail account creation on ingest
        logger.warning("note ingest failed for %s: %s", account_id, exc)


def _summary(account: Dict[str, Any]) -> Dict[str, Any]:
    """Project a seed account onto the inbox summary shape."""

    return {
        "account_id": account["account_id"],
        "name": account.get("name", account["account_id"]),
        "domain": account.get("domain", ""),
        "health_score": account.get("health_score"),
        "risk_level": account.get("risk_level", "medium"),
        "last_signal": account.get("last_signal", account.get("summary", "")),
        "arr": account.get("arr", 0),
    }


def _signals(account: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the signal timeline from the account's active signals."""

    signals: List[Dict[str, Any]] = []
    for key in account.get("active_signals", []) or []:
        signals.append(
            {
                "ts": account.get("renewal_date", ""),
                "key": key,
                "label": _humanize(key),
                "source_type": "signal",
            }
        )
    return signals


async def _memory_history(account_id: str) -> List[Dict[str, Any]]:
    """Pull prior episodes for this account from memory, if available."""

    try:
        from app.agents import safe_get_memory
    except Exception:  # noqa: BLE001
        return []

    memory = await safe_get_memory()
    if memory is None:
        return []

    try:
        episodes = await memory.recall_similar(account_id, "account history", k=5)
    except Exception:  # noqa: BLE001
        return []

    history: List[Dict[str, Any]] = []
    for ep in episodes or []:
        rec = ep.get("recommendation") or {}
        action = rec.get("action") or {
            "key": ep.get("action_key", ""),
            "title": ep.get("action_key", ""),
        }
        outcome = ep.get("outcome") or {}
        history.append(
            {
                "created_at": ep.get("created_at") or ep.get("ts") or "",
                "action": action,
                "status": outcome.get("status") or outcome.get("decision") or "proposed",
                "reason": outcome.get("reason") or ep.get("situation", ""),
                "confidence": (rec.get("confidence") or {}).get("score"),
                "episode_id": ep.get("episode_id") or ep.get("id"),
            }
        )
    return history


class AccountIn(BaseModel):
    """Payload to create an account in the caller's org."""

    name: str = Field(description="Account / company display name.")
    domain: str = Field(default="customer_success", description="Domain pack the account belongs to.")
    industry: Optional[str] = Field(default=None)
    segment: Optional[str] = Field(default=None)
    arr: Optional[float] = Field(default=None, description="Annual recurring revenue.")
    health_score: Optional[float] = Field(default=None)
    risk_level: Optional[str] = Field(default=None, description="critical / high / medium / low.")
    owner: Optional[str] = Field(default=None, description="Account owner / CSM.")
    renewal_date: Optional[str] = Field(default=None)
    signals: Optional[List[Any]] = Field(
        default=None, description="Active signals as keys, or {key,label} objects."
    )
    notes: Optional[str] = Field(default=None, description="Free-text context, also ingested as evidence.")


class AccountUpdate(BaseModel):
    """Partial update for an existing account (only set fields are applied)."""

    name: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    segment: Optional[str] = None
    arr: Optional[float] = None
    health_score: Optional[float] = None
    risk_level: Optional[str] = None
    owner: Optional[str] = None
    renewal_date: Optional[str] = None
    signals: Optional[List[Any]] = None
    notes: Optional[str] = None


def _build_account(account_id: str, body: AccountIn) -> Dict[str, Any]:
    """Assemble the stored account record from a create payload."""

    signal_keys = _normalize_signals(body.signals)
    account: Dict[str, Any] = {
        "account_id": account_id,
        "name": body.name,
        "domain": body.domain or "customer_success",
        "industry": body.industry,
        "segment": body.segment,
        "arr": body.arr if body.arr is not None else 0,
        "health_score": body.health_score,
        "risk_level": (body.risk_level or "medium"),
        "owner": body.owner,
        "renewal_date": body.renewal_date or "",
        "active_signals": signal_keys,
    }
    if body.notes:
        account["notes"] = body.notes
    # A readable last-signal line drives the inbox row preview.
    if signal_keys:
        account["last_signal"] = _humanize(signal_keys[0])
    elif body.notes:
        account["last_signal"] = body.notes.strip()[:140]
    return account


@router.post("/accounts", status_code=201)
async def create_account(
    body: AccountIn, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Create an account in the caller's org and return its inbox summary.

    A stable ``account_id`` is generated, the record is upserted under the org,
    and any ``notes`` are ingested as retrievable evidence for that account.
    """

    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="name must not be empty")

    account = _build_account(_gen_account_id(), body)
    await _persist_account(org_id, account)

    if body.notes and body.notes.strip():
        await _ingest_notes(
            text=body.notes,
            account_id=account["account_id"],
            name=account["name"],
            domain=account["domain"],
        )

    return _summary(account)


@router.post("/accounts/import-demo")
async def import_demo(org_id: str = Depends(current_org)) -> Dict[str, int]:
    """Copy the Demo seed accounts into the caller's org (idempotent).

    Populates a brand-new workspace in one click. Each seed account is upserted
    under the current org, so re-running imports the same set without dupes.
    """

    imported = 0
    for acc in _seed_accounts(None):
        account = dict(acc)
        account.setdefault("domain", "customer_success")
        await _persist_account(org_id, account)
        imported += 1
    return {"imported": imported}


@router.put("/accounts/{account_id}")
async def update_account(
    account_id: str,
    body: AccountUpdate,
    org_id: str = Depends(current_org),
) -> Dict[str, Any]:
    """Update fields on an existing account in the caller's org."""

    existing = await _org_account(org_id, account_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="account not found")

    account = dict(existing)
    fields = body.model_dump(exclude_unset=True)
    if "signals" in fields:
        account["active_signals"] = _normalize_signals(fields.pop("signals"))
    account.update({k: v for k, v in fields.items() if v is not None})
    account["account_id"] = account_id

    await _persist_account(org_id, account)

    if body.notes and body.notes.strip():
        await _ingest_notes(
            text=body.notes,
            account_id=account_id,
            name=account.get("name", account_id),
            domain=account.get("domain", "customer_success"),
        )

    return _summary(account)


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Remove an account from the caller's org."""

    removed = await _delete_account(org_id, account_id)
    if not removed:
        raise HTTPException(status_code=404, detail="account not found")
    return {"deleted": account_id}


@router.get("/accounts")
async def list_accounts(
    domain: Optional[str] = None, org_id: str = Depends(current_org)
) -> List[Dict[str, Any]]:
    """Return the triage inbox summaries for the caller's org, highest risk first.

    Pass ``?domain=`` to scope the inbox to one vertical; omit it for the full
    cross-domain queue. A new org with no accounts returns an empty list.
    """

    accounts = await _org_accounts(org_id, domain)
    summaries = sorted(
        (_summary(a) for a in accounts),
        key=lambda a: (
            _RISK_ORDER.get(a["risk_level"], 4),
            a["health_score"] if a["health_score"] is not None else 100,
        ),
    )
    return summaries


@router.get("/accounts/{account_id}")
async def get_account(
    account_id: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Return the account 360: profile, signal timeline, history, current rec."""

    account = await _org_account(org_id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")

    domain = account.get("domain", "")
    # Profile carries every scalar field on the account (skip the list fields
    # rendered separately).
    profile = {
        k: v
        for k, v in account.items()
        if k not in {"active_signals"}
    }

    history = await _memory_history(account_id)

    # Recent documents give the 360 view its citeable backing material.
    docs = _documents_by_account(domain).get(account_id, [])
    documents = [
        {
            "id": d.get("id"),
            "source_type": d.get("source_type"),
            "title": d.get("title"),
            "excerpt": (d.get("text") or "")[:280],
        }
        for d in docs[:8]
    ]

    return {
        "profile": profile,
        "signals": _signals(account),
        "history": history,
        "documents": documents,
        "current": None,
    }
