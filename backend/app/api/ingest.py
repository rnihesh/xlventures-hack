"""Ingestion API: a real, live connector for workflow step 1.

Turns a pasted or uploaded interaction (meeting note, transcript, email, CRM
rows, support ticket) into citeable, retrievable evidence so the next decision
run grounds on it immediately. Fully offline-safe: the in-memory corpus is always
updated; pgvector persistence is added transparently when a database is set.

Endpoints:
  * ``POST /ingest``         -> ingest raw text, returns chunks written + ids.
  * ``GET  /ingest/sources`` -> recognized source types for the UI select.
  * ``POST /ingest/web``     -> optional live web-search ingest (best-effort).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.retrieval.connectors import (
    TextImportConnector,
    WebSearchConnector,
    recognized_sources,
)

logger = logging.getLogger("app.api.ingest")

router = APIRouter(tags=["ingest"])

_text_connector = TextImportConnector()
_web_connector = WebSearchConnector()


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


@router.post("/ingest")
async def ingest(body: IngestIn) -> Dict[str, Any]:
    """Ingest raw interaction text and make it retrievable in the next run."""
    if not (body.text or "").strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    try:
        result = await _text_connector.ingest(
            text=body.text,
            source_type=body.source_type,
            title=body.title,
            account_id=body.account_id,
            domain=body.domain,
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean error, never 500-trace
        logger.exception("ingest failed")
        raise HTTPException(status_code=500, detail=f"ingest failed: {exc}") from exc

    if not result.ok:
        raise HTTPException(status_code=422, detail=result.detail or "nothing ingested")
    return result.to_dict()


@router.post("/ingest/web")
async def ingest_web(body: WebIngestIn) -> Dict[str, Any]:
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
        )
    except Exception as exc:  # noqa: BLE001 - never hard-fail the optional path
        logger.warning("web ingest failed: %s", exc)
        return {
            "ok": False,
            "chunks_written": 0,
            "ids": [],
            "source_type": "web",
            "domain": body.domain,
            "detail": "web search unavailable",
        }
    return result.to_dict()
