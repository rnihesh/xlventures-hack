"""Policy API.

Exposes the declarative guardrail layer so the UI can render it and so a
recommendation can be checked against a domain's rules on demand.

* ``GET  /policy/{domain}``   the domain's declared policy rules.
* ``POST /policy/evaluate``   evaluate a recommendation against those rules.

Both endpoints are deterministic and offline-safe: rules come from the domain
pack (with built-in fallbacks) and evaluation is pure (no LLM, no database).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.policy.engine import evaluate, evaluation_summary
from app.policy.rules import load_policies

router = APIRouter(tags=["policy"])


class EvaluateRequest(BaseModel):
    """Body for ``POST /policy/evaluate``."""

    recommendation: Dict[str, Any] = Field(default_factory=dict)
    account_id: Optional[str] = None
    domain: str = "customer_success"


def _lookup_account(account_id: Optional[str], domain: str) -> Dict[str, Any]:
    """Best-effort account context by id.

    Uses the accounts seed when available so policies that read account fields
    (ARR, cooldown) have data; otherwise returns a minimal context. Never raises.
    """

    base: Dict[str, Any] = {"account_id": account_id or "", "domain": domain}
    if not account_id:
        return base
    try:
        from app.api.accounts import _BY_ID  # type: ignore

        account = _BY_ID.get(account_id)
        if account:
            return {**account, "domain": account.get("domain", domain)}
    except Exception:  # noqa: BLE001 - accounts slice optional
        pass
    return base


@router.get("/policy/{domain}")
async def get_policy(domain: str) -> Dict[str, Any]:
    """Return the declared policy rules for a domain."""

    rules = load_policies(domain)
    return {
        "domain": domain,
        "policies": [rule.model_dump() for rule in rules],
    }


@router.post("/policy/evaluate")
async def evaluate_policy(req: EvaluateRequest) -> Dict[str, Any]:
    """Evaluate a recommendation against a domain's policy rules."""

    rules = load_policies(req.domain)
    account = _lookup_account(req.account_id, req.domain)
    results: List[Dict[str, Any]] = evaluate(req.recommendation, account, rules)
    summary = evaluation_summary(results)
    return {
        "domain": req.domain,
        "account_id": req.account_id,
        "results": results,
        "summary": summary,
        "requires_approval": summary["requires_approval"],
    }
