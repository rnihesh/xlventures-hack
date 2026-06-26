"""Evaluation API.

GET /eval returns the aggregated suite scores and the headline business
outcome, per the platform interface:

    {
      "suites":   [{name, metric, score, passed, total}, ...],
      "outcomes": {kpi, baseline, projected, unit}
    }

It serves the last cached run for snappy dashboard loads and recomputes on
demand (``?refresh=true`` or when no cache exists). All scoring runs offline.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from app.eval.runner import load_cached, run_all

router = APIRouter(tags=["eval"])


@router.get("/eval")
async def get_eval(refresh: bool = Query(False, description="Force a fresh run")) -> Dict[str, Any]:
    """Return suites + outcomes, from cache when available unless refresh=true."""

    if not refresh:
        cached = load_cached()
        if cached is not None:
            return cached

    return await run_all()
