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
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import seed_data
from app.api._ingest_signals import recent_store
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


class _SeedAccountIndex:
    """Lazy, read-only ``.get(account_id)`` view over the seeded demo accounts.

    Best-effort account context source for the planner, policy, execute, and
    what-if slices (they ``from app.api.accounts import _BY_ID`` and call
    ``.get(account_id)``). Lazy so importing this module stays cheap and the seed
    IO only runs on first lookup. The seed corpus is the shared, org-agnostic
    demo reference data and this view is read-only, so it is not a tenant
    boundary: runtime org-owned accounts are served by ``_org_account`` instead.
    """

    def get(self, account_id: str, default: Any = None) -> Any:
        return _accounts_by_id().get(account_id, default)


# Module-level alias used by best-effort context lookups elsewhere. Without it
# those callers silently fell back to an empty account context, so account-scoped
# policy rules (ARR thresholds, cooldowns) never saw the account's real fields.
_BY_ID = _SeedAccountIndex()


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
    *, text: str, account_id: str, name: str, domain: str, org_id: str
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
            org_id=org_id,
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


async def _memory_history(org_id: str, account_id: str) -> List[Dict[str, Any]]:
    """Pull prior episodes for this account from memory, if available.

    Org-scoped: recall is bound to the caller's tenant so the account 360 never
    surfaces another org's episodes, even when two orgs share an account id (e.g.
    both imported the demo seed accounts, which have fixed ids).
    """

    try:
        from app.agents import safe_get_memory
    except Exception:  # noqa: BLE001
        return []

    memory = await safe_get_memory()
    if memory is None:
        return []

    # List THIS account's episodes for the org (durable, every one), rather than
    # a vector recall that can return nothing. Mirrors the account timeline so the
    # "Past recommendations" section is consistent with it.
    try:
        from app.api._org import DEMO_ORG

        rows = []
        for ep in memory.all_episodes():
            ep_org = getattr(ep, "org_id", None) or DEMO_ORG
            if ep_org != org_id:
                continue
            if str(getattr(ep, "account_id", "")) != str(account_id):
                continue
            rows.append(ep.model_dump() if hasattr(ep, "model_dump") else dict(ep))
        episodes = sorted(
            rows, key=lambda e: e.get("created_at") or "", reverse=True
        )
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
        # Match the run-history shape the UI reads (rationale + confidence object)
        # so memory-sourced rows render with the same fidelity as live runs.
        confidence = rec.get("confidence")
        if not isinstance(confidence, dict):
            confidence = {"score": confidence} if confidence is not None else {}
        history.append(
            {
                "created_at": ep.get("created_at") or ep.get("ts") or "",
                "action": action,
                "status": outcome.get("status") or outcome.get("decision") or "proposed",
                "rationale": rec.get("rationale")
                or rec.get("reasoning")
                or outcome.get("reason")
                or ep.get("situation", ""),
                "confidence": confidence,
                "episode_id": ep.get("episode_id") or ep.get("id"),
            }
        )
    return history


def _retriever_doc_text(domain: str, doc_id: str) -> str:
    """Best-effort full text for an ingested document from the live corpus.

    The text/paste connectors register every ingested document in the in-process
    retriever (``get_retriever(domain)._documents``) keyed by its unique doc id,
    so this resolves the original text for an org's interaction without a
    database. Returns ``""`` when the corpus does not hold it (e.g. a fresh
    process backed only by pgvector); callers then fall back to extracted
    signals. Never raises.
    """

    if not doc_id:
        return ""
    try:
        from app.retrieval.store import get_retriever

        retriever = get_retriever(domain or "customer_success")
        return retriever._documents.get(doc_id, "") or ""
    except Exception:  # noqa: BLE001 - excerpt is best-effort, never fail the read
        return ""


def _interaction_excerpt(
    rec: Dict[str, Any], domain: str, limit: int = 600
) -> Optional[str]:
    """A readable excerpt for an ingested interaction record.

    Prefers the original document text from the live corpus; falls back to the
    deterministically extracted signal phrases (always present on the record) so
    an excerpt is available even when the corpus text is not. Trimmed to ``limit``
    characters. Returns ``None`` when there is nothing to show.
    """

    doc_id = rec.get("doc_id") or rec.get("id") or ""
    text = _retriever_doc_text(domain, str(doc_id))
    if not text:
        phrases = [
            s.get("text", "")
            for s in (rec.get("extracted_signals") or [])
            if isinstance(s, dict)
        ]
        text = " ".join(p for p in phrases if p)
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _ingested_documents(
    org_id: str, account_id: str, domain: str
) -> List[Dict[str, Any]]:
    """The caller org's ingested interactions for an account, newest first.

    Sourced from the org-scoped recent-ingest feed (strictly the caller's
    tenant), each carrying a title, source type, an excerpt of the original
    interaction, and a timestamp. This is what makes a user's uploaded
    crm-notes / transcript / email actually appear on the account 360.
    """

    out: List[Dict[str, Any]] = []
    for rec in recent_store.list(org_id, account_id=account_id, limit=100):
        doc_id = rec.get("doc_id") or rec.get("id") or ""
        out.append(
            {
                "id": rec.get("id") or doc_id or rec.get("ts"),
                "doc_id": doc_id,
                "source_type": rec.get("source_type") or "document",
                "title": rec.get("title") or "Interaction ingested",
                "excerpt": _interaction_excerpt(rec, domain),
                "ts": rec.get("ts"),
            }
        )
    return out


async def _db_documents(org_id: str, account_id: str) -> List[Dict[str, Any]]:
    """Durable ingested documents for an account, from the pgvector table.

    Uploaded crm-notes / transcript / email chunks persist in ``document_chunks``
    (org + account scoped), so they survive restarts (the in-memory feed does
    not). Distinct documents are reconstructed by ``doc_id`` with the first chunk
    as the excerpt. Returns [] when there is no database or no rows.
    """

    pool = await get_pool()
    if pool is None or not account_id:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT doc_id,
                   max(title) AS title,
                   max(source_type) AS source_type,
                   max(created_at) AS created_at,
                   (array_agg(text ORDER BY start_char))[1] AS first_text
            FROM document_chunks
            WHERE org_id = $1 AND account_id = $2
            GROUP BY doc_id
            ORDER BY max(created_at) DESC
            LIMIT 100
            """,
            org_id,
            account_id,
        )
    except Exception:  # noqa: BLE001 - durable docs are best effort
        return []

    out: List[Dict[str, Any]] = []
    for r in rows:
        excerpt = (r["first_text"] or "").strip()
        if len(excerpt) > 280:
            excerpt = excerpt[:279].rstrip() + "…"
        created = r["created_at"]
        out.append(
            {
                "id": r["doc_id"],
                "doc_id": r["doc_id"],
                "source_type": r["source_type"] or "document",
                "title": r["title"] or "Interaction ingested",
                "excerpt": excerpt,
                "ts": created.isoformat() if hasattr(created, "isoformat") else created,
            }
        )
    return out


def _runs_history(org_id: str, account_id: str) -> List[Dict[str, Any]]:
    """Prior NBA runs for this account that produced a recommendation.

    Reads the org-scoped in-memory run registry so a completed run (and its human
    decision, reflected in the recommendation's status) surfaces under "Past
    recommendations and outcomes". Org-scoped: only the caller's runs for this
    account are returned.
    """

    try:
        from app.api.runs import _RUNS
    except Exception:  # noqa: BLE001 - runs slice optional
        return []

    history: List[Dict[str, Any]] = []
    for run in _RUNS.values():
        if run.get("org_id") != org_id or run.get("account_id") != account_id:
            continue
        rec = run.get("recommendation")
        if not rec:
            continue
        action = rec.get("action") or {
            "key": rec.get("action_key", ""),
            "title": _humanize(rec.get("action_key", "Recommendation")),
            "description": "",
        }
        history.append(
            {
                "id": rec.get("id") or run.get("run_id"),
                "run_id": run.get("run_id"),
                "account_id": account_id,
                "domain": run.get("domain"),
                "action": action,
                "rationale": rec.get("rationale") or rec.get("reasoning") or "",
                "status": rec.get("status") or "proposed",
                "confidence": rec.get("confidence") or {},
                "expected_impact": rec.get("expected_impact"),
                "evidence": rec.get("evidence") or [],
                "created_at": run.get("created_at"),
                "episode_id": run.get("episode_id"),
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
            org_id=org_id,
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
            org_id=org_id,
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

    # History: the org's real runs for this account (richest), plus any memory
    # episodes not already represented by a run. Newest first; empty stays empty.
    runs_hist = _runs_history(org_id, account_id)
    seen_eps = {h.get("episode_id") for h in runs_hist if h.get("episode_id")}
    history = runs_hist + [
        h for h in await _memory_history(org_id, account_id)
        if h.get("episode_id") not in seen_eps
    ]
    history.sort(key=lambda h: h.get("created_at") or "", reverse=True)

    # Documents: the caller org's own ingested interactions for this account
    # (uploaded crm-notes / transcript / email all show here), newest first. The
    # seeded demo corpus is appended only for the Demo org so other tenants never
    # see it.
    documents: List[Dict[str, Any]] = []
    seen_docs: set[Any] = set()
    # Durable first: documents persisted in the pgvector table survive restarts.
    for d in await _db_documents(org_id, account_id):
        if d["id"] in seen_docs:
            continue
        documents.append(
            {
                "id": d["id"],
                "source_type": d["source_type"],
                "title": d["title"],
                "excerpt": d["excerpt"] or "",
                "ts": d["ts"],
            }
        )
        seen_docs.add(d["id"])
    # Then any this-process in-memory ingests not yet reflected above.
    for d in _ingested_documents(org_id, account_id, domain):
        if d["id"] in seen_docs:
            continue
        documents.append(
            {
                "id": d["id"],
                "source_type": d["source_type"],
                "title": d["title"],
                "excerpt": d["excerpt"] or "",
                "ts": d["ts"],
            }
        )
        seen_docs.add(d["id"])

    if org_id == DEMO_ORG:
        for d in _documents_by_account(domain).get(account_id, [])[:8]:
            if d.get("id") in seen_docs:
                continue
            documents.append(
                {
                    "id": d.get("id"),
                    "source_type": d.get("source_type"),
                    "title": d.get("title"),
                    "excerpt": (d.get("text") or "")[:280],
                    "ts": d.get("ts") or d.get("created_at") or d.get("date"),
                }
            )

    return {
        "profile": profile,
        "signals": _signals(account),
        "history": history,
        "documents": documents,
        "current": None,
    }


# ---------------------------------------------------------------------------
# Account 360 timeline (read-only audit trail)
# ---------------------------------------------------------------------------
# A merged, time-ordered view of everything the platform knows about one
# account: interactions that landed, NBA runs that recommended an action, the
# human decision on each, and any outcome learned. It is read-only and pulls
# from the existing accounts / ingest / memory stores (no re-run), so it stays
# offline-safe and strictly org-scoped (the account fetch enforces the tenant).

# Human-readable label per recorded decision verb.
_DECISION_TITLE = {
    "accepted": "Approved and sent",
    "edited": "Edited then sent",
    "rejected": "Declined",
}


def _iso(value: Any) -> Optional[str]:
    """Coerce a timestamp (epoch seconds or ISO string) into an ISO8601 string.

    Returns ``None`` when there is no usable timestamp so events without a known
    time sort to the bottom (oldest) of the newest-first timeline.
    """

    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def _summarize_metrics(metrics: Dict[str, Any]) -> Optional[str]:
    """Render recorded outcome metrics as a compact ``key value`` summary."""

    if not metrics:
        return None
    parts = [f"{k.replace('_', ' ')}: {v}" for k, v in metrics.items()]
    return ", ".join(parts)


async def _interaction_events(
    org_id: str, account_id: str, domain: str
) -> List[Dict[str, Any]]:
    """Ingested interactions for the account: durable docs plus demo seed docs."""

    events: List[Dict[str, Any]] = []
    seen: set[Any] = set()

    # Durable first (survive restarts), then this-process in-memory ingests. Each
    # carries an excerpt of the original text so the row can expand to read it.
    merged = list(await _db_documents(org_id, account_id))
    db_ids = {d["id"] for d in merged}
    merged += [
        d for d in _ingested_documents(org_id, account_id, domain) if d["id"] not in db_ids
    ]
    for d in merged:
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        excerpt = d["excerpt"]
        events.append(
            {
                "id": f"ingest:{d['id']}",
                "kind": "interaction",
                "ts": _iso(d["ts"]),
                "title": d["title"],
                "summary": (excerpt[:200] if excerpt else None),
                "text": excerpt,
                "source_type": d["source_type"],
            }
        )

    # Seed corpus documents belong to the Demo org only, so other tenants never
    # see them (strict org-scoping).
    if org_id == DEMO_ORG:
        for doc in _documents_by_account(domain).get(account_id, []):
            body = (doc.get("text") or "").strip()
            text = (body[:599].rstrip() + "…") if len(body) > 600 else (body or None)
            events.append(
                {
                    "id": f"doc:{doc.get('id')}",
                    "kind": "interaction",
                    "ts": _iso(doc.get("ts") or doc.get("created_at") or doc.get("date")),
                    "title": doc.get("title") or doc.get("id"),
                    "summary": body[:200] or None,
                    "text": text,
                    "source_type": doc.get("source_type") or "document",
                }
            )
    return events


async def _episode_events(org_id: str, account_id: str) -> List[Dict[str, Any]]:
    """Recommendation, decision, and outcome events from this account's memory."""

    try:
        from app.agents import safe_get_memory
    except Exception:  # noqa: BLE001
        return []

    memory = await safe_get_memory()
    if memory is None:
        return []

    # Hydrate persisted episodes (no-op offline) so the timeline spans history.
    try:
        await memory._ensure_db()
        episodes = memory.all_episodes()
    except Exception:  # noqa: BLE001 - never fail the read on a memory hiccup
        return []

    events: List[Dict[str, Any]] = []
    for ep in episodes:
        # Org-scoping: an unscoped (seed) episode belongs to the Demo org.
        if (getattr(ep, "org_id", None) or DEMO_ORG) != org_id:
            continue
        if ep.account_id != account_id:
            continue

        rec = ep.recommendation or {}
        action = rec.get("action") or {
            "key": ep.action_key,
            "title": _humanize(ep.action_key or "Recommendation"),
        }
        confidence = rec.get("confidence") or {}
        events.append(
            {
                "id": f"{ep.id}:rec",
                "kind": "recommendation",
                "ts": _iso(ep.created_at),
                "title": action.get("title") or ep.action_key,
                "summary": rec.get("rationale") or rec.get("reasoning") or ep.situation,
                "action": action,
                "confidence": {
                    "score": confidence.get("score"),
                    "label": confidence.get("label"),
                    "method": confidence.get("method"),
                },
                "episode_id": ep.id,
            }
        )

        outcome = ep.outcome
        if outcome is None or outcome.decision == "pending":
            continue

        decided_ts = _iso(getattr(outcome, "recorded_at", None)) or _iso(ep.created_at)
        events.append(
            {
                "id": f"{ep.id}:decision",
                "kind": "decision",
                "ts": decided_ts,
                "title": _DECISION_TITLE.get(outcome.decision, outcome.decision),
                "summary": outcome.reason,
                "decision": outcome.decision,
                "reason": outcome.reason,
                "episode_id": ep.id,
            }
        )

        if outcome.metrics:
            events.append(
                {
                    "id": f"{ep.id}:outcome",
                    "kind": "outcome",
                    "ts": decided_ts,
                    "title": "Outcome learned",
                    "summary": _summarize_metrics(outcome.metrics),
                    "metrics": outcome.metrics,
                    "episode_id": ep.id,
                }
            )
    return events


@router.get("/accounts/{account_id}/timeline")
async def get_account_timeline(
    account_id: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Return the merged, newest-first audit timeline for one account.

    Folds together ingested interactions, NBA recommendations, the human
    decision on each, and any recorded outcome into a single time-ordered
    stream, so the full workflow and memory are visible per account. Read-only,
    offline-safe, and org-scoped: the account fetch 404s for accounts the caller
    does not own, and only that org's interactions and episodes are merged.
    """

    account = await _org_account(org_id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")

    domain = account.get("domain", "")
    events = await _interaction_events(org_id, account_id, domain)
    events += await _episode_events(org_id, account_id)

    # Newest first. Events without a known timestamp sort to the bottom so the
    # "interaction came in -> recommended -> decided -> learned" story reads top
    # to bottom with the most recent activity first.
    events.sort(key=lambda e: e.get("ts") or "", reverse=True)

    counts = {"interaction": 0, "recommendation": 0, "decision": 0, "outcome": 0}
    for ev in events:
        counts[ev["kind"]] = counts.get(ev["kind"], 0) + 1
    counts["total"] = len(events)

    return {
        "account_id": account_id,
        "name": account.get("name", account_id),
        "events": events,
        "counts": counts,
    }
