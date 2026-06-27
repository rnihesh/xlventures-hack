"""File / paste import connector (the primary, always-on ingestion path).

Accepts raw interaction text a human pasted or uploaded (a meeting note, a call
transcript, an email, a CSV of CRM rows, a support ticket) and turns it into
citeable, retrievable evidence. Works fully offline with no database and no
OpenAI key: chunking is local and embeddings fall back to the deterministic hash
encoder.

CSV-ish payloads (header row plus comma/tab rows) are lightly flattened into one
``"Column: value"`` line per cell so each row chunks into a readable, citeable
record instead of a wall of delimiters. Plain prose passes through untouched.
"""

from __future__ import annotations

import csv
import io
from typing import Any, List, Optional

from .base import Connector, IngestResult, ingest_text


def _looks_like_csv(text: str) -> bool:
    """Heuristic: multiple delimited rows with a consistent column count."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    delim = "\t" if "\t" in lines[0] else ","
    if delim not in lines[0]:
        return False
    header_cols = len(lines[0].split(delim))
    if header_cols < 2:
        return False
    consistent = sum(
        1 for ln in lines[1:6] if abs(len(ln.split(delim)) - header_cols) <= 1
    )
    return consistent >= min(2, len(lines) - 1)


def _flatten_csv(text: str) -> str:
    """Render delimited rows as labeled ``Column: value`` blocks for citation.

    Returns the original text unchanged if parsing fails for any reason.
    """
    try:
        delim = "\t" if "\t" in text.splitlines()[0] else ","
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        rows = [r for r in reader if any(cell.strip() for cell in r)]
        if len(rows) < 2:
            return text
        header = [h.strip() or f"col_{i}" for i, h in enumerate(rows[0])]
        blocks: List[str] = []
        for r in rows[1:]:
            pairs = [
                f"{header[i]}: {cell.strip()}"
                for i, cell in enumerate(r)
                if i < len(header) and cell.strip()
            ]
            if pairs:
                blocks.append(". ".join(pairs) + ".")
        return "\n".join(blocks) if blocks else text
    except Exception:  # noqa: BLE001 - never fail ingestion on a parse quirk
        return text


class TextImportConnector(Connector):
    """Ingest pasted or uploaded interaction text. The default offline path."""

    name = "text_import"

    async def ingest(
        self,
        *,
        text: str,
        source_type: str = "document",
        title: Optional[str] = None,
        account_id: Optional[str] = None,
        domain: str = "customer_success",
        org_id: Optional[str] = None,
        **_: Any,
    ) -> IngestResult:
        """Normalize tabular payloads, then funnel through the shared ingest."""
        payload = text or ""
        if _looks_like_csv(payload):
            payload = _flatten_csv(payload)
        return await ingest_text(
            text=payload,
            source_type=source_type,
            title=title,
            account_id=account_id,
            domain=domain,
            org_id=org_id,
        )
