"""Retrieval specialist.

Grounds the run in span-cited evidence. Uses the retrieval slice's
``get_retriever`` when available (hybrid lexical plus optional embeddings) and
falls back to deterministic offline evidence otherwise. Every record carries a
character span so the UI can link a claim back to its source.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents import default_evidence, make_step, safe_get_retriever
from app.packs.loader import load_pack
from app.packs.registry import register_agent


def _query_for(state: Dict[str, Any]) -> str:
    """Compose a retrieval query from the signal and the decision point."""

    signal = state.get("signal") or {}
    content = signal.get("content") or signal.get("type") or "account risk"
    decision_point = state.get("decision_point") or ""
    return f"{decision_point} {content}".strip()


async def _evidence_via_retriever(
    account_id: str, query: str, k: int
) -> List[Dict[str, Any]]:
    """Call the retrieval slice and normalize Evidence objects to dicts."""

    retriever = await safe_get_retriever()
    if retriever is None:
        return []
    try:
        results = await retriever.search(query, account_id=account_id, k=k)
    except TypeError:
        # Tolerate a retriever whose signature omits the keyword.
        results = await retriever.search(query, account_id, k)
    except Exception:  # noqa: BLE001 - never break the run on retrieval failure
        return []

    evidence: List[Dict[str, Any]] = []
    for item in results or []:
        if hasattr(item, "model_dump"):
            evidence.append(item.model_dump())
        elif isinstance(item, dict):
            evidence.append(item)
    return evidence


@register_agent(
    capability="retrieval",
    description="Hybrid retrieval of span-cited evidence grounding the decision.",
    output_keys=["evidence"],
    cost_tier="standard",
    tags=["read", "retrieval"],
)
async def node(state: Dict[str, Any]) -> Dict[str, Any]:
    account_id = state.get("account_id", "unknown-account")
    query = _query_for(state)

    evidence = await _evidence_via_retriever(account_id, query, k=5)
    source = "retriever"
    if not evidence:
        evidence = default_evidence(account_id)
        source = "offline_fallback"

    # Enrich evidence with the pack's retrieval source labels where possible.
    try:
        pack = load_pack(state.get("domain", "customer_success"))
        known = {s.source_type for s in pack.retrieval_sources}
    except Exception:  # noqa: BLE001
        known = set()

    grounded = [e for e in evidence if e.get("source_type") in known] if known else evidence

    return {
        "evidence": evidence,
        "messages": [
            {
                "role": "retrieval",
                "content": f"Retrieved {len(evidence)} evidence snippets ({source}).",
            }
        ],
        "steps": [
            make_step(
                "retrieval",
                f"Retrieved {len(evidence)} span-cited snippets",
                {
                    "evidence_count": len(evidence),
                    "grounded_count": len(grounded),
                    "source": source,
                    "query": query,
                },
            )
        ],
    }
