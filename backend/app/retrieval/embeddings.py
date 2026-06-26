"""Optional OpenAI embeddings with a numpy cosine ranker.

This module is a strict no-op when either the OpenAI API key or numpy is
unavailable, so the retriever transparently falls back to lexical-only search.
Network calls are best-effort: any failure returns ``None`` and the caller
degrades gracefully rather than raising.
"""

from __future__ import annotations

from app.config import settings

try:  # numpy is optional at runtime
    import numpy as np

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - environment without numpy
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

_EMBED_MODEL = "text-embedding-3-small"
_OPENAI_URL = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")


def embeddings_available() -> bool:
    """True only when a key is configured and numpy is importable."""
    return bool(settings.openai_api_key) and _HAS_NUMPY


async def embed_texts(texts: list[str]):
    """Embed ``texts`` via OpenAI, returning an ``(n, d)`` float32 matrix or ``None``.

    Returns ``None`` on any error (no key, no numpy, network/HTTP failure) so the
    retriever falls back to lexical ranking without interruption.
    """
    if not texts or not embeddings_available():
        return None
    try:
        import httpx

        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": _EMBED_MODEL, "input": texts}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{_OPENAI_URL}/embeddings", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        ordered = sorted(data, key=lambda d: d["index"])
        matrix = np.asarray([row["embedding"] for row in ordered], dtype="float32")
        return matrix
    except Exception:
        return None


def cosine_rank(query_vec, matrix, k: int = 10) -> list[tuple[int, float]]:
    """Rank rows of ``matrix`` by cosine similarity to ``query_vec``.

    Returns ``(row_index, similarity)`` pairs sorted descending.
    """
    if not _HAS_NUMPY or matrix is None or query_vec is None:
        return []
    q = np.asarray(query_vec, dtype="float32").reshape(-1)
    m = np.asarray(matrix, dtype="float32")
    if m.size == 0 or q.size == 0:
        return []
    q_norm = q / (np.linalg.norm(q) + 1e-8)
    m_norm = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-8)
    sims = m_norm @ q_norm
    order = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in order]
