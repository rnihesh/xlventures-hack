"""Live ingestion connectors.

Connectors turn real-world interactions into citeable, retrievable evidence and
funnel through ``ingest_text`` so the file/paste path works fully offline while
durable pgvector persistence kicks in automatically when a database is present.

- :class:`TextImportConnector`: paste / upload (primary, always-on, offline-safe).
- :class:`WebSearchConnector`: optional live web search (guarded, degrades).
"""

from __future__ import annotations

from .base import (
    Connector,
    IngestResult,
    ingest_text,
    normalize_source_type,
    recognized_sources,
)
from .text_import import TextImportConnector
from .web_search import WebSearchConnector

__all__ = [
    "Connector",
    "IngestResult",
    "ingest_text",
    "normalize_source_type",
    "recognized_sources",
    "TextImportConnector",
    "WebSearchConnector",
]
