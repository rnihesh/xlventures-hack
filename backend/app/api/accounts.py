"""Accounts API.

Serves the triage inbox and the account 360 view from a deterministic synthetic
seed, enriched with prior recommendation history pulled from memory when the
memory slice is available. The seed is internally consistent (signals match the
narrative) so the use case reads as real rather than random.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["accounts"])


# ---------------------------------------------------------------------------
# Synthetic seed corpus. Each account is internally consistent: the signals,
# health score, and risk level tell one coherent story.
# ---------------------------------------------------------------------------
_SEED: List[Dict[str, Any]] = [
    {
        "account_id": "ACC-1001",
        "name": "Acme Robotics",
        "domain": "customer_success",
        "health_score": 41,
        "risk_level": "high",
        "last_signal": "Usage down 38% QoQ; sponsor disengaged",
        "arr": 240000,
        "profile": {
            "industry": "Industrial Automation",
            "segment": "Enterprise",
            "renewal_in_days": 21,
            "owner": "Priya Nair",
            "seats": 120,
            "active_seats": 74,
        },
        "signals": [
            {"ts": "2026-03-02", "key": "usage_drop", "label": "Weekly active seats fell 120 to 74", "source_type": "usage_metric"},
            {"ts": "2026-04-10", "key": "champion_departure", "label": "VP Ops sponsor left the account", "source_type": "crm_note"},
            {"ts": "2026-05-18", "key": "qbr_missed", "label": "Q2 business review declined", "source_type": "calendar_event"},
            {"ts": "2026-06-05", "key": "renewal_window_open", "label": "Renewal 21 days out", "source_type": "crm_record"},
        ],
        "history": [
            {
                "created_at": "2026-04-15",
                "action": {"key": "launch_adoption_campaign", "title": "Launch a targeted adoption campaign"},
                "status": "rejected",
                "reason": "Too light for an exec-sponsor loss; needed a senior save motion.",
                "confidence": 0.62,
            }
        ],
    },
    {
        "account_id": "ACC-1002",
        "name": "Northwind Logistics",
        "domain": "customer_success",
        "health_score": 68,
        "risk_level": "medium",
        "last_signal": "Feature adoption stalled on analytics module",
        "arr": 96000,
        "profile": {
            "industry": "Logistics",
            "segment": "Mid-Market",
            "renewal_in_days": 88,
            "owner": "Marcus Lee",
            "seats": 60,
            "active_seats": 52,
        },
        "signals": [
            {"ts": "2026-05-01", "key": "feature_abandonment", "label": "Analytics module adoption reversed", "source_type": "usage_metric"},
            {"ts": "2026-05-22", "key": "login_decline", "label": "Logins down 12% MoM", "source_type": "usage_metric"},
        ],
        "history": [],
    },
    {
        "account_id": "ACC-1003",
        "name": "Helios Health",
        "domain": "customer_success",
        "health_score": 82,
        "risk_level": "low",
        "last_signal": "Seat utilization near cap; expansion intent",
        "arr": 310000,
        "profile": {
            "industry": "Healthcare",
            "segment": "Enterprise",
            "renewal_in_days": 140,
            "owner": "Dana Cole",
            "seats": 200,
            "active_seats": 191,
        },
        "signals": [
            {"ts": "2026-06-01", "key": "seat_growth", "label": "Utilization at 95% of license cap", "source_type": "usage_metric"},
            {"ts": "2026-06-12", "key": "expansion_intent", "label": "Buyer asked about additional modules", "source_type": "crm_note"},
        ],
        "history": [
            {
                "created_at": "2026-03-20",
                "action": {"key": "schedule_executive_business_review", "title": "Schedule an executive business review"},
                "status": "approved",
                "reason": "QBR surfaced expansion appetite.",
                "confidence": 0.81,
            }
        ],
    },
    {
        "account_id": "ACC-1004",
        "name": "Vertex Financial",
        "domain": "customer_success",
        "health_score": 35,
        "risk_level": "high",
        "last_signal": "Billing dispute open; support escalations spiking",
        "arr": 178000,
        "profile": {
            "industry": "Financial Services",
            "segment": "Enterprise",
            "renewal_in_days": 47,
            "owner": "Priya Nair",
            "seats": 90,
            "active_seats": 61,
        },
        "signals": [
            {"ts": "2026-05-10", "key": "invoice_dispute", "label": "Disputed Q2 true-up invoice", "source_type": "billing_event"},
            {"ts": "2026-05-28", "key": "support_ticket_spike", "label": "Escalations up 3x in two weeks", "source_type": "support_ticket"},
            {"ts": "2026-06-08", "key": "negative_sentiment", "label": "Negative tone on last two calls", "source_type": "crm_note"},
        ],
        "history": [],
    },
    {
        "account_id": "ACC-2001",
        "name": "Brightwave Media",
        "domain": "saas_sales",
        "health_score": 60,
        "risk_level": "medium",
        "last_signal": "Opportunity stalled in negotiation 18 days",
        "arr": 0,
        "profile": {
            "industry": "Media",
            "segment": "Mid-Market",
            "stage": "Negotiation",
            "owner": "Sam Ortiz",
            "deal_size": 64000,
        },
        "signals": [
            {"ts": "2026-06-01", "key": "stage_stall", "label": "Stuck in Negotiation 18 days", "source_type": "crm_record"},
            {"ts": "2026-06-14", "key": "no_recent_activity", "label": "No buyer reply in 9 days", "source_type": "crm_note"},
        ],
        "history": [],
    },
]

_BY_ID: Dict[str, Dict[str, Any]] = {a["account_id"]: a for a in _SEED}


def _summary(account: Dict[str, Any]) -> Dict[str, Any]:
    """Project a seed account onto the inbox summary shape."""

    return {
        "account_id": account["account_id"],
        "name": account["name"],
        "domain": account["domain"],
        "health_score": account["health_score"],
        "risk_level": account["risk_level"],
        "last_signal": account["last_signal"],
        "arr": account["arr"],
    }


async def _memory_history(account_id: str) -> List[Dict[str, Any]]:
    """Pull prior episodes for this account from memory, if available."""

    try:
        from app.agents import safe_get_memory
    except Exception:  # noqa: BLE001
        return []

    memory = await safe_get_memory()
    if memory is None:
        return []

    try:
        episodes = await memory.recall_similar(account_id, "account history", k=5)
    except Exception:  # noqa: BLE001
        return []

    history: List[Dict[str, Any]] = []
    for ep in episodes or []:
        rec = ep.get("recommendation") or {}
        action = rec.get("action") or {"key": ep.get("action_key", ""), "title": ep.get("action_key", "")}
        outcome = ep.get("outcome") or {}
        history.append(
            {
                "created_at": ep.get("created_at") or ep.get("ts") or "",
                "action": action,
                "status": outcome.get("status") or outcome.get("decision") or "proposed",
                "reason": outcome.get("reason") or ep.get("situation", ""),
                "confidence": (rec.get("confidence") or {}).get("score"),
                "episode_id": ep.get("episode_id") or ep.get("id"),
            }
        )
    return history


@router.get("/accounts")
async def list_accounts() -> List[Dict[str, Any]]:
    """Return the triage inbox summaries, highest risk first."""

    order = {"high": 0, "medium": 1, "low": 2}
    accounts = sorted(
        (_summary(a) for a in _SEED),
        key=lambda a: (order.get(a["risk_level"], 3), a["health_score"]),
    )
    return list(accounts)


@router.get("/accounts/{account_id}")
async def get_account(account_id: str) -> Dict[str, Any]:
    """Return the account 360: profile, signal timeline, history, current rec."""

    account = _BY_ID.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")

    profile = {
        "account_id": account["account_id"],
        "name": account["name"],
        "domain": account["domain"],
        "health_score": account["health_score"],
        "risk_level": account["risk_level"],
        "arr": account["arr"],
        **account.get("profile", {}),
    }

    # Seed history plus anything memory has learned for this account.
    history = list(account.get("history", []))
    history.extend(await _memory_history(account_id))

    current: Optional[Dict[str, Any]] = None

    return {
        "profile": profile,
        "signals": account.get("signals", []),
        "history": history,
        "current": current,
    }
