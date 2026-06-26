"""Component suite: retrieval faithfulness and citation grounding.

Two real, deterministic metrics (an optional LLM-as-judge can refine them, but
the defaults compute fully offline):

* Citation Grounding: every recommendation must cite well-formed evidence whose
  character spans are valid and whose required source ids (from the golden case)
  are actually present. A case passes only when all its must-cite sources appear
  and every evidence span indexes a real substring of its snippet.

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
    snippet = evidence.get("snippet") or ""
    span = evidence.get("span") or {}
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    if start < 0 or end < start or end > len(snippet):
        return False
    if not evidence.get("source_id") or not evidence.get("source_type"):
        return False
    return bool(evidence.get("claim"))


def _format_required(case: Dict[str, Any]) -> List[str]:
    account_id = case.get("account_id", "")
    return [tpl.format(account_id=account_id) for tpl in case.get("must_cite", [])]


def score_grounding(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Each case passes when spans are valid and all required sources are cited."""

    total = len(records)
    passed = 0
    details: List[Dict[str, Any]] = []
    for rec in records:
        evidence = (rec.get("recommendation") or {}).get("evidence") or []
        produced_ids = {e.get("source_id") for e in evidence}
        spans_ok = len(evidence) > 0 and all(_span_valid(e) for e in evidence)
        required = _format_required(rec["case"])
        missing = [src for src in required if src not in produced_ids]
        ok = spans_ok and not missing
        passed += int(ok)
        details.append(
            {
                "id": rec["case"]["id"],
                "spans_ok": spans_ok,
                "missing_sources": missing,
                "grounded": ok,
            }
        )
    score = passed / total if total else 0.0
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
