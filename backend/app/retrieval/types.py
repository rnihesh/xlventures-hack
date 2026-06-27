"""Typed models for the retrieval subsystem.

The :class:`Evidence` model is the frozen interface contract shared across
backend slices. Its shape mirrors the ``evidence`` items in
``contracts/recommendation.schema.json`` (claim, source_id, source_type,
snippet, span) plus a retrieval ``score`` used for ranking and confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


class Span(BaseModel):
    """Character offsets of a snippet within its source document text."""

    start: int = Field(ge=0, description="Start character offset of the snippet.")
    end: int = Field(ge=0, description="End character offset (exclusive) of the snippet.")


class Evidence(BaseModel):
    """A single piece of grounding evidence retrieved from the corpus.

    ``span`` indexes into the *source document text* so the frontend can render
    an exact, auditable citation (highlight ``source_text[start:end]``).
    """

    claim: str = Field(description="Short statement the snippet supports.")
    source_id: str = Field(description="Identifier of the source document.")
    source_type: str = Field(description="Source type, e.g. meeting_notes, call_transcript.")
    snippet: str = Field(description="Exact excerpt from the source backing the claim.")
    span: Span = Field(description="Character span of the snippet within the source text.")
    score: float = Field(description="Retrieval relevance score in [0, 1] (1 = most relevant).")


@dataclass(frozen=True)
class Chunk:
    """An indexable unit of a source document with exact char spans.

    ``text`` is the verbatim chunk (so ``source_text[start:end] == text``) while
    ``context`` is an enriched string (title + source type + text) used only for
    lexical and embedding matching, never surfaced as a citation.
    """

    chunk_id: str
    doc_id: str
    account_id: str | None
    source_type: str
    title: str
    text: str
    start: int
    end: int
    context: str
    # Owning org for tenant scoping. None means shared knowledge (the seeded
    # corpus) visible to every org; an org id restricts the chunk to that org so
    # one tenant never retrieves another tenant's ingested evidence.
    org_id: str | None = None
