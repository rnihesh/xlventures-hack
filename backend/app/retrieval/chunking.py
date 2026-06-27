"""Contextual chunking with exact character spans.

Documents are split into small, citeable chunks while preserving the precise
character offsets into the *original* document text. Each chunk also carries a
``context`` string (title + source type + body) that improves lexical and
embedding recall without polluting the verbatim citation snippet.
"""

from __future__ import annotations

import re

from .types import Chunk

# Target/maximum chunk sizes in characters. Paragraphs under the target are kept
# whole (best for tight, readable citations); longer ones are windowed by
# sentence while keeping spans contiguous and exact.
_TARGET_CHARS = 360
_MAX_CHARS = 520

_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*", re.UNICODE)


def _split_with_spans(text: str, sep: str) -> list[tuple[str, int, int]]:
    """Split ``text`` on ``sep`` returning (piece, start, end) with exact spans.

    ``text[start:end] == piece`` for every returned tuple.
    """
    parts: list[tuple[str, int, int]] = []
    cursor = 0
    for piece in text.split(sep):
        start = cursor
        end = cursor + len(piece)
        parts.append((piece, start, end))
        cursor = end + len(sep)
    return parts


def _sentence_windows(piece: str, base: int) -> list[tuple[int, int]]:
    """Window a long paragraph into ~target-sized (start, end) spans.

    Spans are global offsets (``base`` + local) and stay contiguous so the
    original text slice is preserved verbatim.
    """
    windows: list[tuple[int, int]] = []
    win_start: int | None = None
    win_end: int | None = None
    for match in _SENTENCE_RE.finditer(piece):
        s = base + match.start()
        e = base + match.end()
        if win_start is None:
            win_start, win_end = s, e
            continue
        if (e - win_start) <= _MAX_CHARS:
            win_end = e
        else:
            windows.append((win_start, win_end))  # type: ignore[arg-type]
            win_start, win_end = s, e
        if win_end is not None and (win_end - win_start) >= _TARGET_CHARS:
            windows.append((win_start, win_end))
            win_start, win_end = None, None
    if win_start is not None and win_end is not None:
        windows.append((win_start, win_end))
    return windows


def chunk_document(
    *,
    doc_id: str,
    account_id: str | None,
    source_type: str,
    title: str,
    text: str,
    org_id: str | None = None,
) -> list[Chunk]:
    """Split a single document into contextual chunks with exact spans.

    ``org_id`` stamps each chunk with its owning tenant (None = shared/seed
    knowledge) so the retriever can keep one org's ingested evidence private.
    """
    chunks: list[Chunk] = []

    def _emit(start: int, end: int) -> None:
        # Trim leading/trailing whitespace while keeping span/text in sync.
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        body = text[start:end]
        if len(body.strip()) < 3:
            return
        context = f"{title} ({source_type}). {body}"
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}::{len(chunks)}",
                doc_id=doc_id,
                account_id=account_id,
                source_type=source_type,
                title=title,
                text=body,
                start=start,
                end=end,
                context=context,
                org_id=org_id,
            )
        )

    for piece, p_start, p_end in _split_with_spans(text, "\n"):
        if not piece.strip():
            continue
        if len(piece) <= _MAX_CHARS:
            _emit(p_start, p_end)
        else:
            for w_start, w_end in _sentence_windows(piece, p_start):
                _emit(w_start, w_end)

    # Fallback: never lose a document with unusual formatting.
    if not chunks and text.strip():
        _emit(0, len(text))
    return chunks
