"""Retrieval subsystem: hybrid lexical + optional embedding search over a
seeded Customer Success corpus, returning span-cited Evidence.

Public surface (frozen interface):
    Evidence            - pydantic evidence model (claim, source_id, ...)
    Retriever           - async search(query, account_id, k=5) -> list[Evidence]
    get_retriever()     - factory returning a cached Retriever
"""

from __future__ import annotations

from .store import Retriever, get_retriever
from .types import Evidence, Span

__all__ = ["Evidence", "Span", "Retriever", "get_retriever"]
