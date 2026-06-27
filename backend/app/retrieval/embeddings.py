"""Optional OpenAI embeddings with a numpy cosine ranker.

This module is a strict no-op when either the OpenAI API key or numpy is
unavailable, so the retriever transparently falls back to lexical-only search.
Network calls are best-effort: any failure returns ``None`` and the caller
degrades gracefully rather than raising.
"""

from __future__ import annotations

import hashlib
import re

from app.config import settings

try:  # numpy is optional at runtime
    import numpy as np

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - environment without numpy
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

_EMBED_MODEL = "text-embedding-3-small"
# Output dimension of the OpenAI model above; the pgvector columns and the
# deterministic offline fallback below all use this exact width so vectors are
# interchangeable between the two encoders.
EMBED_DIM = 1536
_OPENAI_URL = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


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
            body = resp.json()
            data = body["data"]
        try:
            from app.usage import record_embedding

            record_embedding(_EMBED_MODEL, (body.get("usage") or {}).get("total_tokens", 0))
        except Exception:  # noqa: BLE001 - accounting never breaks retrieval
            pass
        ordered = sorted(data, key=lambda d: d["index"])
        matrix = np.asarray([row["embedding"] for row in ordered], dtype="float32")
        return matrix
    except Exception:
        return None


def _hash_embed_one(text: str):
    """Deterministic bag-of-tokens hashed embedding, L2-normalized.

    A signed feature-hashing trick maps each token into one of ``EMBED_DIM``
    buckets. The result is reproducible across processes (so an offline ingest
    and an offline query produce matchable vectors) and lives in the same
    geometry as the OpenAI vectors (unit norm, cosine-comparable).
    """
    vec = np.zeros(EMBED_DIM, dtype="float32")
    for tok in _TOKEN_RE.findall((text or "").lower()):
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % EMBED_DIM
        sign = 1.0 if (digest[4] & 1) else -1.0
        vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec /= norm
    return vec


def hash_embed(texts: list[str]):
    """Deterministic offline embeddings for ``texts`` as an ``(n, EMBED_DIM)``
    matrix, or ``None`` when numpy is unavailable."""
    if not _HAS_NUMPY or not texts:
        return None
    return np.asarray([_hash_embed_one(t) for t in texts], dtype="float32")


async def embed_for_index(texts: list[str]) -> tuple[object | None, str]:
    """Embed ``texts`` for indexing/querying, returning ``(matrix, method)``.

    Prefers real OpenAI embeddings when a key is configured; otherwise falls
    back to the deterministic local hash embedding so ingestion and pgvector
    queries still work fully offline. ``method`` is ``"openai"``, ``"hash"`` or
    ``"none"`` (numpy missing / empty input).
    """
    if not texts:
        return None, "none"
    matrix = await embed_texts(texts)
    if matrix is not None:
        return matrix, "openai"
    fallback = hash_embed(texts)
    if fallback is not None:
        return fallback, "hash"
    return None, "none"


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
