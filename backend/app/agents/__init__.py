"""Specialist agents and shared helpers.

Importing this package registers every specialist into the agent registry (see
``app.packs.registry.AGENTS``). The planner imports this package so the
capabilities are available when the graph is built.

Helpers here intentionally degrade gracefully: when the retrieval or memory
slices are not present (or fail to construct), the loaders return ``None`` and
specialists fall back to deterministic, offline behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    """Current UTC time as an ISO8601 string."""

    return datetime.now(timezone.utc).isoformat()


def make_step(node: str, summary: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a trace step record appended to ``state['steps']``."""

    return {"node": node, "summary": summary, "ts": now_iso(), "data": data or {}}


async def safe_get_retriever() -> Optional[Any]:
    """Return a Retriever from the retrieval slice, or None if unavailable."""

    try:
        from app.retrieval.store import get_retriever  # type: ignore
    except Exception:  # noqa: BLE001 - slice may not exist yet
        return None
    try:
        retriever = get_retriever()
        if hasattr(retriever, "__await__"):
            retriever = await retriever  # type: ignore[assignment]
        return retriever
    except Exception:  # noqa: BLE001
        return None


async def safe_get_memory() -> Optional[Any]:
    """Return a Memory from the memory slice, or None if unavailable."""

    try:
        from app.memory.store import get_memory  # type: ignore
    except Exception:  # noqa: BLE001 - slice may not exist yet
        return None
    try:
        memory = get_memory()
        if hasattr(memory, "__await__"):
            memory = await memory  # type: ignore[assignment]
        return memory
    except Exception:  # noqa: BLE001
        return None


def default_evidence(account_id: str) -> List[Dict[str, Any]]:
    """Span-cited evidence used when the retrieval slice supplies none.

    Each item matches the Evidence shape in the frozen contract (claim,
    source_id, source_type, snippet, span, score).
    """

    snippet_a = (
        "Product usage for this account dropped 38% quarter over quarter, with "
        "weekly active seats falling from 120 to 74."
    )
    snippet_b = (
        "The economic buyer has not attended a business review in 2 quarters and "
        "the renewal is 95 days out."
    )
    snippet_c = (
        "Support sentiment is neutral with two open tickets, both low severity and "
        "trending toward resolution."
    )
    return [
        {
            "claim": "Usage is declining sharply ahead of renewal.",
            "source_id": f"telemetry:{account_id}:q-usage",
            "source_type": "usage_metric",
            "snippet": snippet_a,
            "span": {"start": 0, "end": 38},
            "score": 0.91,
        },
        {
            "claim": "Executive sponsor engagement has lapsed.",
            "source_id": f"crm:{account_id}:engagement",
            "source_type": "crm_note",
            "snippet": snippet_b,
            "span": {"start": 0, "end": 49},
            "score": 0.84,
        },
        {
            "claim": "Support sentiment is not a primary driver of risk.",
            "source_id": f"support:{account_id}:tickets",
            "source_type": "support_ticket",
            "snippet": snippet_c,
            "span": {"start": 0, "end": 36},
            "score": 0.55,
        },
    ]


def evidence_to_schema(item: Dict[str, Any]) -> Dict[str, Any]:
    """Project an Evidence record onto the recommendation schema's 5 fields."""

    span = item.get("span") or {"start": 0, "end": 0}
    return {
        "claim": item.get("claim", ""),
        "source_id": item.get("source_id", ""),
        "source_type": item.get("source_type", ""),
        "snippet": item.get("snippet", ""),
        "span": {
            "start": int(span.get("start", 0)),
            "end": int(span.get("end", 0)),
        },
    }


# Import specialist modules so their @register_agent decorators run. These are
# imported last so the helpers above are already defined when each module does
# ``from app.agents import ...``.
from app.agents import (  # noqa: E402,F401
    critic,
    drafter,
    outcome_simulator,
    play_recommender,
    retrieval_agent,
    risk_scorer,
)

__all__ = [
    "now_iso",
    "make_step",
    "safe_get_retriever",
    "safe_get_memory",
    "default_evidence",
    "evidence_to_schema",
]
