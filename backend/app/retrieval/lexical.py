"""Pure-Python BM25 lexical ranker.

No third-party dependencies: works fully offline and is the default ranker when
embeddings are unavailable. Implements Okapi BM25 over tokenized chunk context.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Keep alphanumerics; numbers matter for this corpus ("38" from "-38%", seat
# counts, ARR figures). A small stopword set trims noise without hurting recall.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """
    a an the and or of to in on at for with by is are was were be been being this that these those
    it its as from we our you your they their he she his her i me my mine our ours us them
    has have had do does did will would shall should can could may might must not no yes
    """.split()
)

_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    """Lowercase, regex-tokenize and drop stopwords."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


class BM25Index:
    """In-memory BM25 index over a fixed list of documents (chunks)."""

    def __init__(self, documents: list[str]) -> None:
        self._doc_tokens: list[list[str]] = [tokenize(d) for d in documents]
        self._doc_len: list[int] = [len(t) for t in self._doc_tokens]
        self._n = len(self._doc_tokens)
        self._avgdl = (sum(self._doc_len) / self._n) if self._n else 0.0

        self._term_freqs: list[Counter[str]] = [Counter(t) for t in self._doc_tokens]
        df: Counter[str] = Counter()
        for tf in self._term_freqs:
            df.update(tf.keys())
        # BM25+ style idf, floored at a small positive value to avoid negatives.
        self._idf: dict[str, float] = {
            term: math.log(1.0 + (self._n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def search(self, query: str, k: int = 10) -> list[tuple[int, float]]:
        """Return up to ``k`` ``(doc_index, score)`` pairs sorted by score desc."""
        q_terms = tokenize(query)
        if not q_terms or self._n == 0:
            return []
        scores: list[float] = [0.0] * self._n
        for term in q_terms:
            idf = self._idf.get(term)
            if idf is None:
                continue
            for idx in range(self._n):
                freq = self._term_freqs[idx].get(term)
                if not freq:
                    continue
                denom = freq + _K1 * (1.0 - _B + _B * self._doc_len[idx] / (self._avgdl or 1.0))
                scores[idx] += idf * (freq * (_K1 + 1.0)) / denom
        ranked = [(i, s) for i, s in enumerate(scores) if s > 0.0]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:k]
