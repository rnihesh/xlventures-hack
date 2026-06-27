"""Retrieval specialist.

Grounds the run in span-cited evidence. Instead of a single query, it runs a
small multi-query expansion: it derives 2 to 3 sub-queries from the signal and
the classified decision point, retrieves for each, then merges and de-duplicates
by source document, keeping the best-scored citation per source. This broadens
recall (a usage drop and a lapsed sponsor surface different documents) while
keeping every record span-cited.

Sub-query generation is deterministic and offline by default: sub-queries are
built from signal keywords plus the pack's decision-point synonyms (the decision
point label, its primary KPI, and its trigger-signal labels). When a real LLM is
configured it may propose the sub-queries instead, but the deterministic path is
always the fallback so the node never depends on a key.
"""

from __future__ import annotations

import asyncio

from typing import Any, Dict, List, Tuple

from app.agents import default_evidence, make_step, safe_get_retriever
from app.agents.tools import decision_point_synonyms, keyword_tokens, llm_lines
from app.packs.loader import load_pack
from app.packs.registry import register_agent

# How many sub-queries to run (including the base query) and how many evidence
# items to keep after merging.
_MAX_SUBQUERIES = 3
_KEEP = 5


def _base_query(state: Dict[str, Any]) -> str:
    """The primary query: decision point plus the raw signal content."""

    signal = state.get("signal") or {}
    content = signal.get("content") or signal.get("type") or "account risk"
    decision_point = state.get("decision_point") or ""
    return f"{decision_point} {content}".strip()


def _deterministic_subqueries(state: Dict[str, Any], pack: Any) -> List[str]:
    """Derive sub-queries from signal keywords plus decision-point synonyms.

    Fully offline and stable: the same state always yields the same expansion.
    """

    signal = state.get("signal") or {}
    content = signal.get("content") or signal.get("type") or ""
    decision_point = state.get("decision_point") or ""

    keywords = keyword_tokens(content, 6)
    synonyms = decision_point_synonyms(pack, decision_point)

    subqueries: List[str] = []
    # 1. The signal in its own keywords (focuses on what actually fired).
    if keywords:
        subqueries.append(" ".join(keywords))
    # 2. Decision-point synonyms (label, KPI, trigger-signal labels).
    if synonyms:
        subqueries.append(" ".join(synonyms[:6]))
    # 3. A blended query that ties the signal to the decision-point theme.
    if keywords and synonyms:
        subqueries.append(" ".join(keywords[:3] + synonyms[:3]))

    return subqueries


def _llm_subqueries(state: Dict[str, Any]) -> List[str]:
    """Sub-queries for multi-query retrieval.

    Uses the deterministic keyword/synonym expansion only. We deliberately skip
    an LLM call here: it added a slow serial OpenAI round-trip to every run for
    little gain over the deterministic expansion, so retrieval stays fast.
    """

    return []


def _plan_queries(state: Dict[str, Any], pack: Any) -> List[str]:
    """Assemble the ordered, de-duplicated query plan (base query first).

    When the clarify loop has populated ``gap_queries`` (a re-retrieve driven by
    the gap-analysis node), those gap-targeted queries are prepended so the
    second retrieval pass focuses on the missing facts, and the fan-out cap is
    widened to fit them.
    """

    gap_queries = [str(q) for q in (state.get("gap_queries") or []) if q]

    queries: List[str] = [_base_query(state)]
    # Gap-targeted queries lead on a clarify re-retrieve so they are not capped out.
    queries.extend(gap_queries)

    expansion = _llm_subqueries(state)
    if not expansion:
        expansion = _deterministic_subqueries(state, pack)
    queries.extend(expansion)

    # De-duplicate while preserving order and capping the total fan-out. The cap
    # grows by the number of gap queries so a clarify pass never drops them.
    cap = _MAX_SUBQUERIES + 1 + len(gap_queries)
    seen: set[str] = set()
    plan: List[str] = []
    for q in queries:
        norm = " ".join((q or "").split()).strip()
        key = norm.lower()
        if not norm or key in seen:
            continue
        seen.add(key)
        plan.append(norm)
        if len(plan) >= cap:
            break
    return plan


async def _search(
    retriever: Any, query: str, account_id: str, k: int, org_id: str = "org_demo"
) -> List[Dict[str, Any]]:
    """Run one retriever search and normalize results to dicts. Never raises."""

    try:
        results = await retriever.search(
            query, account_id=account_id, k=k, org_id=org_id
        )
    except TypeError:
        # Tolerate a retriever whose signature omits the keyword.
        try:
            results = await retriever.search(query, account_id, k)
        except Exception:  # noqa: BLE001
            return []
    except Exception:  # noqa: BLE001 - never break the run on retrieval failure
        return []

    out: List[Dict[str, Any]] = []
    for item in results or []:
        if hasattr(item, "model_dump"):
            out.append(item.model_dump())
        elif isinstance(item, dict):
            out.append(item)
    return out


async def _multi_retrieve(
    account_id: str,
    queries: List[str],
    k: int,
    domain: str,
    org_id: str = "org_demo",
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Retrieve for each query, then merge and de-duplicate by source document.

    Keeps the highest-scored citation per ``source_id`` so a document that ranks
    well for several sub-queries is represented once, by its strongest span.
    Returns the merged evidence (best-scored first) and a per-query hit count.
    """

    retriever = await safe_get_retriever(domain)
    if retriever is None:
        return [], {}

    best: Dict[str, Dict[str, Any]] = {}
    hits: Dict[str, int] = {}
    for query in queries:
        results = await _search(retriever, query, account_id, k, org_id)
        hits[query] = len(results)
        for item in results:
            source_id = item.get("source_id") or item.get("snippet", "")
            score = float(item.get("score", 0.0) or 0.0)
            current = best.get(source_id)
            if current is None or score > float(current.get("score", 0.0) or 0.0):
                merged = dict(item)
                # Record which sub-queries surfaced this source for auditability.
                matched = set((current or {}).get("matched_queries", []))
                matched.add(query)
                merged["matched_queries"] = sorted(matched)
                best[source_id] = merged
            else:
                current.setdefault("matched_queries", [])
                if query not in current["matched_queries"]:
                    current["matched_queries"] = sorted(
                        set(current["matched_queries"]) | {query}
                    )

    merged = sorted(
        best.values(), key=lambda e: float(e.get("score", 0.0) or 0.0), reverse=True
    )
    return merged, hits


@register_agent(
    capability="retrieval",
    description="Multi-query retrieval of span-cited evidence grounding the decision.",
    output_keys=["evidence"],
    cost_tier="standard",
    tags=["read", "retrieval"],
)
async def node(state: Dict[str, Any]) -> Dict[str, Any]:
    account_id = state.get("account_id", "unknown-account")
    domain = state.get("domain", "customer_success")
    # Scope retrieval to the run's owning org so a tenant only grounds on its own
    # ingested evidence (plus shared seed knowledge). Falls back to the demo org
    # for paths that do not set it (eval fallback, single-tenant offline).
    org_id = state.get("org_id") or "org_demo"

    try:
        pack = load_pack(domain)
    except Exception:  # noqa: BLE001
        pack = None

    queries = await asyncio.to_thread(_plan_queries, state, pack)

    evidence, hits = await _multi_retrieve(
        account_id, queries, k=_KEEP, domain=domain, org_id=org_id
    )
    evidence = evidence[:_KEEP]
    source = "retriever"
    if not evidence:
        evidence = default_evidence(account_id)
        source = "offline_fallback"

    # Enrich with the pack's retrieval source labels where possible.
    try:
        known = {s.source_type for s in pack.retrieval_sources} if pack else set()
    except Exception:  # noqa: BLE001
        known = set()
    grounded = [e for e in evidence if e.get("source_type") in known] if known else evidence

    summary = (
        f"Expanded to {len(queries)} queries; merged {len(evidence)} span-cited snippets"
    )
    return {
        "evidence": evidence,
        "messages": [
            {
                "role": "retrieval",
                "content": (
                    f"Ran {len(queries)} sub-queries and merged {len(evidence)} "
                    f"deduplicated evidence snippets ({source})."
                ),
            }
        ],
        "steps": [
            make_step(
                "retrieval",
                summary,
                {
                    "evidence_count": len(evidence),
                    "grounded_count": len(grounded),
                    "source": source,
                    "sub_queries": queries,
                    "query": queries[0] if queries else "",
                    "per_query_hits": hits,
                },
            )
        ],
    }
