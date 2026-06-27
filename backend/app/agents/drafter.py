"""Drafter.

Turns the chosen play into a doable artifact: a personalized outreach email plus
a CRM task stub. Uses the LLM when available, otherwise a deterministic template
so the run always ends in something actionable rather than advice.
"""

from __future__ import annotations

import asyncio

from typing import Any, Dict

from app.agents import make_step
from app.packs.registry import register_agent


def _chosen(state: Dict[str, Any]) -> Dict[str, Any]:
    candidates = state.get("candidate_actions") or []
    for c in candidates:
        if c.get("chosen"):
            return c
    return candidates[0] if candidates else {}


def _llm_draft(state: Dict[str, Any], action: Dict[str, Any]) -> str | None:
    """Ask the LLM for a short outreach email. Returns None on any failure."""

    try:
        from app.deps import get_llm

        llm = get_llm()
    except Exception:  # noqa: BLE001
        return None
    if llm is None:
        return None

    account_id = state.get("account_name") or state.get("account_id", "the account")
    risk = (state.get("risk_opportunity") or {}).get("summary", "")
    prompt = (
        "You are a Customer Success Manager. Draft a concise, warm outreach email "
        f"(under 120 words) to {account_id} to execute this play: "
        f"{action.get('title', '')}. Context: {risk}. "
        "No subject line filler, no placeholders in brackets."
    )
    try:
        result = llm.invoke(prompt)
        text = getattr(result, "content", result)
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:  # noqa: BLE001
        return None
    return None


def _template_draft(state: Dict[str, Any], action: Dict[str, Any]) -> str:
    account_id = state.get("account_name") or state.get("account_id", "your team")
    title = action.get("title", "the recommended next step")
    return (
        "Hi there,\n\n"
        "I have been reviewing how things are going and want to make sure we keep "
        "delivering value for "
        f"{account_id}. I would like to propose that we {title.lower()} so we can "
        "realign on your goals, address recent changes in usage, and lock in the "
        "outcomes you signed up for.\n\n"
        "Are you open to a short session this week? I will come prepared with a "
        "tailored plan and clear next steps.\n\n"
        "Best,\nYour Customer Success team"
    )


@register_agent(
    capability="drafter",
    description="Drafts a personalized email and a CRM task for the chosen play.",
    output_keys=["draft"],
    cost_tier="cheap",
    tags=["artifact", "side_effecting"],
)
async def node(state: Dict[str, Any]) -> Dict[str, Any]:
    action = _chosen(state)
    llm_body = await asyncio.to_thread(_llm_draft, state, action)
    body = llm_body or _template_draft(state, action)
    source = "llm" if llm_body else "template"

    draft = {
        "type": "email",
        "subject": f"Quick proposal: {action.get('title', 'next best action')}",
        "body": body,
        "task": {
            "type": "crm_task",
            "title": f"Execute play: {action.get('title', 'next best action')}",
            "account_id": state.get("account_id"),
            "due_in_days": 3,
            "priority": "high",
        },
        "source": source,
    }

    return {
        "draft": draft,
        "messages": [
            {"role": "drafter", "content": "Drafted outreach email and CRM task."}
        ],
        "steps": [
            make_step(
                "drafter",
                "Drafted outreach email and CRM task",
                {"action": action.get("key"), "source": source},
            )
        ],
    }
