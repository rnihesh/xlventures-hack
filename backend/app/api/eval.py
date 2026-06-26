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

from fastapi import APIRouter, Depends, Query

from app.api._org import current_org
from app.eval.runner import eval_for_org, run_all

router = APIRouter(tags=["eval"])


@router.get("/eval")
async def get_eval(
    refresh: bool = Query(False, description="Re-run the golden suites (slow, uses the LLM)"),
    org_id: str = Depends(current_org),
) -> Dict[str, Any]:
    """Return the engine suites + the requesting org's outcomes.

    Fast by default: serves cached golden-suite scores (global engine quality)
    and computes only the cheap, org-scoped outcomes, so a dashboard load never
    runs the LLM and never hangs. ``?refresh=true`` re-runs the golden cases.
    """

    if refresh:
        return await run_all(org_id)
    return await eval_for_org(org_id)
