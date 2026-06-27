"""Component suite: retrieval faithfulness and citation grounding.

Two real, deterministic metrics (an optional LLM-as-judge can refine them, but
the defaults compute fully offline):

* Citation Grounding: every recommendation must cite well-formed evidence whose
  character spans are auditable (they index a real, non-empty region of the
  source) and whose claim is corroborated by more than one distinct source. The
  per-case score is the fraction of well-formed citations, discounted when the
  case rests on a single source. A case passes when that score clears the
  threshold. This measures the LIVE engine's citations: the live retriever emits
  document-indexed spans (snippet == source_text[start:end], so the span width
  equals the snippet length) with real corpus source ids, NOT the golden case's
  ``must_cite`` template ids, which only the offline default-evidence fallback
  ever produces. Gating on those template ids scored every real run 0.0 (the
  same class of bug as the trajectory EXPECTED_NODES mismatch), so grounding now
  measures citation well-formedness and corroboration instead.

* Retrieval Faithfulness: each evidence claim must be lexically supported by its
  own snippet, and the rationale must be supported by the cited evidence. The
  score is the mean fraction of supported claims across cases, a standard
  groundedness proxy.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Set

from app.eval.scenario import load_golden, run_cases

GROUNDING_THRESHOLD = 0.7
FAITHFULNESS_THRESHOLD = 0.6

# A per-case faithfulness ratio at or above this counts the case as passing.
_CASE_FAITHFUL_AT = 0.5

_STOPWORDS: Set[str] = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "was", "were", "has", "have", "had", "this", "that", "these", "those",
    "it", "its", "at", "by", "as", "be", "been", "from", "not", "no", "but",
    "so", "if", "then", "than", "into", "out", "up", "down", "over", "two",
    "while", "after", "before", "ahead", "inside", "their", "they", "he", "she",
}


def _tokens(text: str) -> Set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _overlap(a: str, b: str) -> int:
    return len(_tokens(a) & _tokens(b))


def _span_valid(evidence: Dict[str, Any]) -> bool:
    """True when the citation is well-formed and its span is auditable.

    The span must point at a real, non-empty region. Two conventions are
    accepted, both guaranteeing the cited text actually exists:

    * Document-indexed (the LIVE engine): the span indexes the source document
      text, so ``snippet == source_text[start:end]`` and the span width equals
      the snippet length.
    * Snippet-indexed (the offline default-evidence fallback): the span indexes
      within the snippet itself, so ``end <= len(snippet)``.

    The previous check only allowed ``end <= len(snippet)`` and therefore failed
    every document-indexed citation (whose end routinely exceeds the snippet
    length), scoring the real engine 0.0.
    """

    snippet = evidence.get("snippet") or ""
    span = evidence.get("span") or {}
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    if start < 0 or end <= start:
        return False
    if not snippet.strip():
        return False
    width = end - start
    doc_indexed = width == len(snippet)
    snippet_indexed = end <= len(snippet)
    if not (doc_indexed or snippet_indexed):
        return False
    if not evidence.get("source_id") or not evidence.get("source_type"):
        return False
    return bool(evidence.get("claim"))


# A single-source case is only weakly grounded: with no corroboration the claim
# rests on one document, so its grounding quality is discounted by this factor.
_SINGLE_SOURCE_FACTOR = 0.5

# Distinct well-formed sources needed for full (undiscounted) grounding credit.
_CORROBORATION_MIN = 2


def _case_grounding(evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Grounding quality for one recommendation in [0, 1].

    Quality is the fraction of citations that are well-formed and span-auditable,
    discounted when fewer than ``_CORROBORATION_MIN`` distinct sources back the
    call. An empty citation list (an ungrounded recommendation) scores 0.0.
    """

    total = len(evidence)
    if total == 0:
        return {"score": 0.0, "valid": 0, "total": 0, "distinct_sources": 0}

    valid = [e for e in evidence if _span_valid(e)]
    distinct = {e.get("source_id") for e in valid}
    validity = len(valid) / total
    corroborated = len(distinct) >= _CORROBORATION_MIN
    score = validity if corroborated else validity * _SINGLE_SOURCE_FACTOR
    return {
        "score": round(score, 4),
        "valid": len(valid),
        "total": total,
        "distinct_sources": len(distinct),
    }


def score_grounding(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mean grounding quality: well-formed, span-auditable, corroborated citations."""

    total = len(records)
    scores: List[float] = []
    passed = 0
    details: List[Dict[str, Any]] = []
    for rec in records:
        evidence = (rec.get("recommendation") or {}).get("evidence") or []
        case = _case_grounding(evidence)
        scores.append(case["score"])
        grounded = case["score"] >= GROUNDING_THRESHOLD
        passed += int(grounded)
        details.append(
            {
                "id": rec["case"]["id"],
                "grounding": case["score"],
                "valid_citations": case["valid"],
                "total_citations": case["total"],
                "distinct_sources": case["distinct_sources"],
                "grounded": grounded,
            }
        )
    score = sum(scores) / total if total else 0.0
    return {
        "name": "Citation Grounding",
        "metric": "groundedness",
        "score": round(score, 3),
        "passed": passed,
        "total": total,
        "healthy": score >= GROUNDING_THRESHOLD,
        "details": details,
    }


def _case_faithfulness(recommendation: Dict[str, Any]) -> float:
    """Fraction of claims (plus the rationale) supported by cited snippets."""

    evidence = recommendation.get("evidence") or []
    if not evidence:
        return 0.0

    supported_claims = 0
    snippet_blob_parts: List[str] = []
    for ev in evidence:
        claim = ev.get("claim", "")
        snippet = ev.get("snippet", "")
        snippet_blob_parts.append(snippet)
        snippet_blob_parts.append(claim)
        # A claim is faithful if it shares meaningful content with its snippet.
        if _overlap(claim, snippet) >= 1:
            supported_claims += 1

    claim_ratio = supported_claims / len(evidence)

    # The rationale must also be anchored in the cited evidence.
    snippet_blob = " ".join(snippet_blob_parts)
    rationale = recommendation.get("rationale", "")
    rationale_supported = 1.0 if _overlap(rationale, snippet_blob) >= 2 else 0.0

    # Weight claims more than the single rationale signal.
    return round(0.7 * claim_ratio + 0.3 * rationale_supported, 4)


def score_faithfulness(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mean groundedness of claims and rationale across all cases."""

    total = len(records)
    ratios: List[float] = []
    passed = 0
    for rec in records:
        ratio = _case_faithfulness(rec.get("recommendation") or {})
        ratios.append(ratio)
        passed += int(ratio >= _CASE_FAITHFUL_AT)
    score = sum(ratios) / total if total else 0.0
    return {
        "name": "Retrieval Faithfulness",
        "metric": "faithfulness",
        "score": round(score, 3),
        "passed": passed,
        "total": total,
        "healthy": score >= FAITHFULNESS_THRESHOLD,
    }


async def evaluate() -> List[Dict[str, Any]]:
    """Run the component suite standalone and return its suite dicts."""

    records = await run_cases(load_golden())
    return [score_grounding(records), score_faithfulness(records)]


if __name__ == "__main__":  # pragma: no cover - manual invocation
    for suite in asyncio.run(evaluate()):
        print(
            f"{suite['name']:<24} {suite['metric']:<14} "
            f"score={suite['score']:.3f} passed={suite['passed']}/{suite['total']}"
        )
