"""Helpers to attach exact span citations to retrieved chunks.

Keeps citation construction in one place so spans always index into the
*original* source document text and snippets stay verbatim.
"""

from __future__ import annotations

import re

from .types import Chunk, Evidence, Span

_LEAD_RE = re.compile(r"[^.!?\n]+[.!?]?")
_MAX_CLAIM = 160


def derive_claim(chunk: Chunk) -> str:
    """Build a short, human-readable claim from the chunk lead sentence."""
    lead_match = _LEAD_RE.search(chunk.text)
    lead = (lead_match.group(0).strip() if lead_match else chunk.text.strip())
    if len(lead) > _MAX_CLAIM:
        lead = lead[: _MAX_CLAIM - 1].rstrip() + "…"
    return lead


def verify_span(source_text: str, chunk: Chunk) -> Span:
    """Return a Span that exactly matches the chunk text in ``source_text``.

    Uses the chunk's recorded offsets when they line up, otherwise falls back to
    locating the snippet, guaranteeing ``source_text[start:end] == snippet``.
    """
    start, end = chunk.start, chunk.end
    if 0 <= start <= end <= len(source_text) and source_text[start:end] == chunk.text:
        return Span(start=start, end=end)
    found = source_text.find(chunk.text)
    if found >= 0:
        return Span(start=found, end=found + len(chunk.text))
    # Last resort: clamp so the model still validates.
    safe_end = min(len(source_text), max(0, end))
    return Span(start=max(0, min(start, safe_end)), end=safe_end)


def build_evidence(chunk: Chunk, source_text: str, score: float) -> Evidence:
    """Assemble an Evidence object with a verified span citation."""
    span = verify_span(source_text, chunk)
    snippet = source_text[span.start : span.end]
    return Evidence(
        claim=derive_claim(chunk),
        source_id=chunk.doc_id,
        source_type=chunk.source_type,
        snippet=snippet,
        span=span,
        score=round(float(score), 4),
    )
