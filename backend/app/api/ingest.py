"""Ingestion API: a real, live connector for workflow step 1.

Turns a pasted or uploaded interaction (meeting note, transcript, email, CRM
rows, support ticket) into citeable, retrievable evidence so the next decision
run grounds on it immediately. Fully offline-safe: the in-memory corpus is always
updated; pgvector persistence is added transparently when a database is set.

Every ingest is org-scoped (the caller's org owns the evidence) and runs a light,
deterministic signal-extraction pass (no LLM): it returns a short title plus a
few candidate signal phrases so the interaction surfaces structured hints the
moment it lands. Repeat pastes are idempotent per org.

Endpoints:
  * ``POST /ingest``         -> ingest raw text, returns id + extracted signals.
  * ``GET  /ingest/sources`` -> recognized source types for the UI select.
  * ``GET  /ingest/recent``  -> the org's recently ingested interactions.
  * ``POST /ingest/web``     -> optional live web-search ingest (best-effort).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api._ingest_signals import (
    content_fingerprint,
    derive_title,
    extract_signals,
    recent_store,
)
from app.api._org import current_org
from app.retrieval.connectors import (
    TextImportConnector,
    WebSearchConnector,
    recognized_sources,
)

logger = logging.getLogger("app.api.ingest")

router = APIRouter(tags=["ingest"])

_text_connector = TextImportConnector()
_web_connector = WebSearchConnector()


def _record_from_result(
    result_dict: Dict[str, Any],
    *,
    title: str,
    signals: List[Dict[str, str]],
    chars: int,
) -> Dict[str, Any]:
    """Project a connector result + extracted signals into the API response.

    Preserves the existing connector fields (``chunks_written``, ``ids``,
    ``persisted`` ...) and adds the ingest-experience fields (``id``,
    ``extracted_signals``, ``chars``, ``title``) the UI surfaces.
    """
    enriched = dict(result_dict)
    enriched["id"] = result_dict.get("doc_id") or ""
    enriched["title"] = title
    enriched["extracted_signals"] = signals
    enriched["chars"] = chars
    enriched["ts"] = enriched.get("ts") or time.time()
    return enriched


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class IngestIn(BaseModel):
    """Raw interaction text to ingest into the retrieval corpus."""

    text: str = Field(description="The raw interaction text (note, transcript, email, CSV rows).")
    source_type: str = Field(default="document", description="Recognized source type key.")
    title: Optional[str] = Field(default=None, description="Optional human title for the import.")
    account_id: Optional[str] = Field(default=None, description="Optional account to scope the evidence to.")
    domain: str = Field(default="customer_success", description="Domain pack the corpus belongs to.")


class WebIngestIn(BaseModel):
    """A live web-search query to fetch and ingest as web evidence."""

    query: str = Field(description="Search query to fetch public context for.")
    account_id: Optional[str] = Field(default=None, description="Optional account to scope to.")
    title: Optional[str] = Field(default=None, description="Optional title override.")
    domain: str = Field(default="customer_success", description="Domain pack the corpus belongs to.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/ingest/sources")
async def list_sources() -> Dict[str, List[Dict[str, str]]]:
    """Return the recognized interaction source types (for the UI select)."""
    return {"sources": recognized_sources()}


@router.get("/ingest/recent")
async def list_recent(
    account_id: Optional[str] = None,
    limit: int = 25,
    org_id: str = Depends(current_org),
) -> Dict[str, List[Dict[str, Any]]]:
    """Return the caller's recently ingested interactions, most recent first.

    Optionally filter by ``account_id``. Org-scoped: an org only ever sees the
    evidence it ingested this process.
    """
    return {"items": recent_store.list(org_id, account_id=account_id, limit=limit)}


@router.post("/ingest")
async def ingest(
    body: IngestIn, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Ingest raw interaction text and make it retrievable in the next run.

    Org-scoped and idempotent: re-pasting the same content for the same account
    returns the original record instead of duplicating evidence. Runs a light,
    deterministic signal-extraction pass so the response carries a short title
    and a few candidate signal phrases (no LLM, fully offline).
    """
    if not (body.text or "").strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    title = derive_title(body.text, body.source_type, body.title)
    signals = extract_signals(body.text)
    chars = len(body.text.strip())

    # Idempotency: a repeat paste for the same org + account + type short-circuits
    # to the stored record so we never double-index the same evidence.
    fingerprint = content_fingerprint(org_id, body.account_id, body.source_type, body.text)
    existing = recent_store.get(org_id, fingerprint)
    if existing is not None:
        return {**existing, "duplicate": True}

    try:
        result = await _text_connector.ingest(
            text=body.text,
            source_type=body.source_type,
            title=title,
            account_id=body.account_id,
            domain=body.domain,
            org_id=org_id,
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean error, never 500-trace
        logger.exception("ingest failed")
        raise HTTPException(status_code=500, detail=f"ingest failed: {exc}") from exc

    if not result.ok:
        raise HTTPException(status_code=422, detail=result.detail or "nothing ingested")

    record = _record_from_result(
        result.to_dict(), title=title, signals=signals, chars=chars
    )
    recent_store.add(org_id, fingerprint, record)
    return {**record, "duplicate": False}


@router.post("/ingest/web")
async def ingest_web(
    body: WebIngestIn, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Optional: run a live web search and ingest its snippets (best-effort).

    Returns ``ok: false`` with a reason when the network is unavailable or the
    query has no public results, so the UI can degrade without an error toast.
    """
    if not (body.query or "").strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    try:
        result = await _web_connector.ingest(
            query=body.query,
            account_id=body.account_id,
            title=body.title,
            domain=body.domain,
            org_id=org_id,
        )
    except Exception as exc:  # noqa: BLE001 - never hard-fail the optional path
        logger.warning("web ingest failed: %s", exc)
        return {
            "ok": False,
            "chunks_written": 0,
            "ids": [],
            "source_type": "web",
            "domain": body.domain,
            "extracted_signals": [],
            "detail": "web search unavailable",
        }

    result_dict = result.to_dict()
    if not result_dict.get("ok"):
        return result_dict

    title = derive_title(
        result_dict.get("title") or body.query, "web", body.title or body.query
    )
    record = _record_from_result(
        result_dict, title=title, signals=[], chars=result_dict.get("chunks_written", 0)
    )
    fingerprint = content_fingerprint(org_id, body.account_id, "web", body.query)
    recent_store.add(org_id, fingerprint, record)
    return record
