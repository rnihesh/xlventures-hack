"""Live web-search connector backed by Serper (google.serper.dev).

Pulls public context for an account or topic from a real Google search and
ingests the result snippets as ``web`` evidence. Strictly best-effort: with no
API key, no network, or any HTTP error it returns a disabled :class:`IngestResult`
rather than raising, so the rest of the app (and the primary file/paste path) is
never blocked by it.

Set ``SERPER_API_KEY`` to enable. Without it, the connector is a graceful no-op.
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.config import settings

from .base import IngestResult, ingest_text

_SERPER_URL = "https://google.serper.dev/search"
_TIMEOUT = 12.0
_MAX_SNIPPETS = 8


async def serper_search(query: str, num: int = 8) -> List[dict]:
    """Return structured Google results via Serper, or [] when unavailable.

    Each item is {"title", "snippet", "link"}. Includes the answer box and
    knowledge graph (when present) ahead of the organic results.
    """
    q = (query or "").strip()
    if not q or not settings.serper_api_key:
        return []
    try:
        import httpx

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _SERPER_URL,
                headers={
                    "X-API-KEY": settings.serper_api_key,
                    "Content-Type": "application/json",
                },
                json={"q": q, "num": num},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 - offline / no key / HTTP error degrades
        return []

    results: List[dict] = []

    ab = data.get("answerBox") or {}
    ab_text = (ab.get("answer") or ab.get("snippet") or "").strip()
    if ab_text:
        results.append(
            {"title": ab.get("title") or "Answer", "snippet": ab_text, "link": ab.get("link", "")}
        )

    kg = data.get("knowledgeGraph") or {}
    kg_text = (kg.get("description") or "").strip()
    if kg_text:
        results.append(
            {"title": kg.get("title") or "Overview", "snippet": kg_text, "link": kg.get("descriptionLink", "")}
        )

    for item in data.get("organic") or []:
        snippet = (item.get("snippet") or "").strip()
        if not snippet:
            continue
        results.append(
            {
                "title": (item.get("title") or "").strip(),
                "snippet": snippet,
                "link": (item.get("link") or "").strip(),
            }
        )
        if len(results) >= num:
            break
    return results[:num]


class WebSearchConnector:
    """Search the live web (Serper) for context and ingest it as ``web`` evidence."""

    name = "web_search"

    async def ingest(
        self,
        *,
        query: str,
        account_id: Optional[str] = None,
        domain: str = "customer_success",
        title: Optional[str] = None,
        org_id: Optional[str] = None,
        **_: Any,
    ) -> IngestResult:
        """Run a live search for ``query`` and ingest the snippets it returns."""
        q = (query or "").strip()
        if not q:
            return IngestResult(
                ok=False, chunks_written=0, source_type="web", domain=domain,
                detail="empty query",
            )
        if not settings.serper_api_key:
            return IngestResult(
                ok=False, chunks_written=0, source_type="web", domain=domain,
                detail="web search not configured (set SERPER_API_KEY)",
            )

        results = await serper_search(q, num=_MAX_SNIPPETS)
        if not results:
            return IngestResult(
                ok=False, chunks_written=0, source_type="web", domain=domain,
                detail="no web results for that query",
            )

        # One readable block per result so the ingested evidence carries the link.
        lines = [
            f"{r['title']}: {r['snippet']}" + (f" ({r['link']})" if r.get("link") else "")
            for r in results
        ]
        text = "\n".join(lines)
        return await ingest_text(
            text=text,
            source_type="web",
            title=title or f"Web search: {q}",
            account_id=account_id,
            domain=domain,
            org_id=org_id,
        )
