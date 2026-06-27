"""Optional live web-search connector (guarded by network, degrades gracefully).

Pulls public context for an account or topic from a live search and ingests the
result snippets as ``web`` evidence. It is strictly best-effort: with no network
(or on any HTTP error) it returns a disabled :class:`IngestResult` rather than
raising, so the rest of the app, and the primary file/paste path, are never
blocked by it.

The default backend is the DuckDuckGo Instant Answer API, which needs no API key
(``https://api.duckduckgo.com/?q=...&format=json``). A custom OpenAI-compatible
or other search endpoint is out of scope here; this stays dependency-light and
offline-safe.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .base import IngestResult, ingest_text

_DDG_URL = "https://api.duckduckgo.com/"
_TIMEOUT = 8.0
_MAX_SNIPPETS = 6


def _collect_snippets(data: dict) -> List[str]:
    """Extract human-readable snippets from a DuckDuckGo IA JSON payload."""
    snippets: List[str] = []

    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        source = (data.get("AbstractSource") or "").strip()
        heading = (data.get("Heading") or "").strip()
        prefix = f"{heading} ({source}): " if heading else ""
        snippets.append(f"{prefix}{abstract}")

    answer = (data.get("Answer") or "").strip()
    if answer:
        snippets.append(answer)

    def _walk(topics: list) -> None:
        for item in topics or []:
            if len(snippets) >= _MAX_SNIPPETS:
                return
            if isinstance(item, dict):
                txt = (item.get("Text") or "").strip()
                if txt:
                    snippets.append(txt)
                elif item.get("Topics"):
                    _walk(item["Topics"])

    _walk(data.get("RelatedTopics") or [])
    return snippets[:_MAX_SNIPPETS]


class WebSearchConnector:
    """Search the live web for context and ingest it as ``web`` evidence."""

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

        try:
            import httpx

            params = {
                "q": q,
                "format": "json",
                "no_html": "1",
                "no_redirect": "1",
                "skip_disambig": "1",
            }
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    _DDG_URL,
                    params=params,
                    headers={"User-Agent": "aperture-nba/0.1"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001 - offline / network failure degrades
            return IngestResult(
                ok=False, chunks_written=0, source_type="web", domain=domain,
                detail="web search unavailable (offline or no results)",
            )

        snippets = _collect_snippets(data)
        if not snippets:
            return IngestResult(
                ok=False, chunks_written=0, source_type="web", domain=domain,
                detail="no web results for that query",
            )

        text = "\n".join(snippets)
        return await ingest_text(
            text=text,
            source_type="web",
            title=title or f"Web search: {q}",
            account_id=account_id,
            domain=domain,
            org_id=org_id,
        )
