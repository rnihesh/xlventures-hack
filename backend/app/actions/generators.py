"""Artifact generators.

Each generator takes a recommendation dict and an account-context dict and
returns a small, typed artifact ready to drop into a real tool:

* ``draft_email``    -> {"subject", "body"}
* ``create_crm_task``-> {"title", "due", "notes", "priority"}
* ``slack_handoff``  -> {"channel", "message"}

When ``OPENAI_API_KEY`` is set the LLM writes the prose; otherwise deterministic
templates built from the recommendation fields are used. No generator requires
the network: the LLM path is only attempted when a key is configured, and any
failure falls back to the template so the result is always populated.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.config import settings

# Artifact types this module knows how to produce.
ARTIFACT_TYPES = ("email", "crm_task", "slack")


# ---------------------------------------------------------------------------
# Field extraction helpers (tolerant of partial recommendations)
# ---------------------------------------------------------------------------


def _action(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Return the recommendation's action object, tolerating missing keys."""

    action = rec.get("action")
    if isinstance(action, dict):
        return action
    return {}


def _action_title(rec: Dict[str, Any]) -> str:
    action = _action(rec)
    title = action.get("title") or rec.get("title") or "the recommended next step"
    return str(title).strip()


def _action_description(rec: Dict[str, Any]) -> str:
    action = _action(rec)
    desc = action.get("description") or rec.get("description") or ""
    return str(desc).strip()


def _action_key(rec: Dict[str, Any]) -> str:
    action = _action(rec)
    return str(action.get("key") or rec.get("action_key") or "next_best_action").strip()


def _rationale(rec: Dict[str, Any]) -> str:
    return str(rec.get("rationale") or "").strip()


def _risk_summary(rec: Dict[str, Any]) -> str:
    risk = rec.get("risk_opportunity")
    if isinstance(risk, dict):
        return str(risk.get("summary") or "").strip()
    return ""


def _expected_impact(rec: Dict[str, Any]) -> str:
    impact = rec.get("expected_impact")
    if isinstance(impact, dict):
        kpi = str(impact.get("kpi") or "").strip()
        estimate = str(impact.get("estimate") or "").strip()
        if kpi and estimate:
            return f"{kpi}: {estimate}"
        return kpi or estimate
    return ""


def _confidence_label(rec: Dict[str, Any]) -> str:
    conf = rec.get("confidence")
    if isinstance(conf, dict):
        return str(conf.get("label") or "").strip()
    return ""


def _account_name(account: Dict[str, Any]) -> str:
    if not isinstance(account, dict):
        return "the account"
    profile = account.get("profile")
    if isinstance(profile, dict) and profile.get("name"):
        return str(profile["name"]).strip()
    return str(
        account.get("name") or account.get("account_id") or "the account"
    ).strip()


def _account_owner(account: Dict[str, Any]) -> str:
    if not isinstance(account, dict):
        return "Customer Success team"
    profile = account.get("profile")
    if isinstance(profile, dict) and profile.get("owner"):
        return str(profile["owner"]).strip()
    return str(account.get("owner") or "Customer Success team").strip()


def _account_id(account: Dict[str, Any]) -> str:
    if not isinstance(account, dict):
        return ""
    return str(account.get("account_id") or "").strip()


# ---------------------------------------------------------------------------
# LLM plumbing (only attempted when a key is configured)
# ---------------------------------------------------------------------------


def _llm_available() -> bool:
    """True only when a real OpenAI key is configured.

    Guards every LLM call so the offline path is taken deterministically when
    no key is present, without ever touching the network.
    """

    return bool(settings.openai_api_key)


def _llm_complete(prompt: str) -> Optional[str]:
    """Run a single prompt through the LLM. Returns None on any failure."""

    if not _llm_available():
        return None
    try:
        from app.deps import get_llm

        llm = get_llm()
        if llm is None:
            return None
        result = llm.invoke(prompt)
        text = getattr(result, "content", result)
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:  # noqa: BLE001 - any LLM/network error falls back to template
        return None
    return None


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON object extraction from an LLM response."""

    if not text:
        return None
    # Strip code fences if the model wrapped the JSON.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    # Fall back to the first balanced-looking object in the string.
    if not fenced:
        brace = re.search(r"\{.*\}", candidate, re.DOTALL)
        if brace:
            candidate = brace.group(0)
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:  # noqa: BLE001
        return None
    return None


def _context_block(rec: Dict[str, Any], account: Dict[str, Any]) -> str:
    """Compact, shared context string handed to the LLM prompts."""

    lines = [
        f"Account: {_account_name(account)}",
        f"Owner: {_account_owner(account)}",
        f"Recommended play: {_action_title(rec)}",
    ]
    if _action_description(rec):
        lines.append(f"Play detail: {_action_description(rec)}")
    if _risk_summary(rec):
        lines.append(f"Situation: {_risk_summary(rec)}")
    if _rationale(rec):
        lines.append(f"Why now: {_rationale(rec)}")
    if _expected_impact(rec):
        lines.append(f"Expected impact: {_expected_impact(rec)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def _template_email(rec: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, str]:
    name = _account_name(account)
    title = _action_title(rec)
    owner = _account_owner(account)
    risk = _risk_summary(rec).rstrip(".")
    impact = _expected_impact(rec)

    subject = f"Quick proposal for {name}: {title}"

    context_line = (
        f" I have been reviewing how things are tracking and {risk[0].lower() + risk[1:]}"
        if risk
        else " I have been reviewing how things are tracking on our side"
    )
    impact_line = (
        f" The goal is concrete: {impact}." if impact else ""
    )

    body = (
        f"Hi {name} team,\n\n"
        f"{context_line.strip()}. I would like to propose that we "
        f"{title[0].lower() + title[1:]} so we can realign on your goals and lock in "
        f"the outcomes you signed up for.{impact_line}\n\n"
        "Are you open to a short session this week? I will come prepared with a "
        "tailored plan and clear next steps.\n\n"
        f"Best,\n{owner}"
    )
    return {"subject": subject, "body": body}


def draft_email(rec: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, str]:
    """Generate a ready-to-send outreach email for the recommended play."""

    if _llm_available():
        prompt = (
            "You are a senior Customer Success Manager. Write a concise, warm "
            "outreach email (under 130 words) that executes the recommended play. "
            "Return STRICT JSON with exactly two keys: \"subject\" and \"body\". "
            "No markdown, no placeholders in brackets, sign off as the owner.\n\n"
            f"{_context_block(rec, account)}"
        )
        raw = _llm_complete(prompt)
        parsed = _extract_json(raw) if raw else None
        if parsed:
            subject = str(parsed.get("subject") or "").strip()
            body = str(parsed.get("body") or "").strip()
            if subject and body:
                return {"subject": subject, "body": body}
    return _template_email(rec, account)


# ---------------------------------------------------------------------------
# CRM task
# ---------------------------------------------------------------------------


def _due_iso(days: int = 3) -> str:
    """An ISO date (no time) ``days`` from now, deterministic per call day."""

    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def _template_crm_task(rec: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, str]:
    name = _account_name(account)
    title = _action_title(rec)
    rationale = _rationale(rec)
    impact = _expected_impact(rec)
    label = _confidence_label(rec)

    notes_parts = [f"Recommended play: {title}."]
    if rationale:
        notes_parts.append(f"Why now: {rationale}")
    if impact:
        notes_parts.append(f"Expected impact: {impact}.")
    if label:
        notes_parts.append(f"Engine confidence: {label}.")
    notes = " ".join(notes_parts)

    high_conf = label.lower() in {"high", "very high"}
    return {
        "title": f"{title} ({name})",
        "due": _due_iso(3),
        "notes": notes,
        "priority": "high" if high_conf else "medium",
    }


def create_crm_task(rec: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, str]:
    """Generate a CRM task stub for the recommended play."""

    base = _template_crm_task(rec, account)
    if _llm_available():
        prompt = (
            "You are a Customer Success operations assistant. Write a CRM follow-up "
            "task for the recommended play. Return STRICT JSON with keys \"title\" "
            "(short, action-first) and \"notes\" (2-3 sentences of context for the "
            "owner). No markdown, no brackets.\n\n"
            f"{_context_block(rec, account)}"
        )
        raw = _llm_complete(prompt)
        parsed = _extract_json(raw) if raw else None
        if parsed:
            title = str(parsed.get("title") or "").strip()
            notes = str(parsed.get("notes") or "").strip()
            if title:
                base["title"] = title
            if notes:
                base["notes"] = notes
    return base


# ---------------------------------------------------------------------------
# Slack handoff
# ---------------------------------------------------------------------------


def _slack_channel(account: Dict[str, Any], rec: Dict[str, Any]) -> str:
    """Derive a plausible Slack channel from the domain or account."""

    domain = ""
    if isinstance(account, dict):
        domain = str(account.get("domain") or "").strip()
    if not domain:
        domain = str(rec.get("domain") or "").strip()
    mapping = {
        "customer_success": "#cs-saves",
        "saas_sales": "#sales-deals",
    }
    return mapping.get(domain, "#account-handoffs")


def _template_slack(rec: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, str]:
    name = _account_name(account)
    owner = _account_owner(account)
    title = _action_title(rec)
    risk = _risk_summary(rec)
    impact = _expected_impact(rec)
    label = _confidence_label(rec)

    lines = [f":handshake: *Handoff: {name}*"]
    if risk:
        lines.append(f"> {risk}")
    lines.append(f"*Recommended play:* {title}")
    if impact:
        lines.append(f"*Expected impact:* {impact}")
    if label:
        lines.append(f"*Confidence:* {label}")
    lines.append(f"*Owner:* {owner}")
    lines.append("React with :white_check_mark: to take it, or reply to discuss.")

    return {
        "channel": _slack_channel(account, rec),
        "message": "\n".join(lines),
    }


def slack_handoff(rec: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, str]:
    """Generate a Slack handoff message for the recommended play."""

    base = _template_slack(rec, account)
    if _llm_available():
        prompt = (
            "You are posting an internal Slack handoff so a teammate can pick up an "
            "account. Write a punchy message (under 80 words) using Slack mrkdwn "
            "(*bold*, > quote, emoji). Return STRICT JSON with a single key "
            "\"message\". No markdown code fences.\n\n"
            f"{_context_block(rec, account)}"
        )
        raw = _llm_complete(prompt)
        parsed = _extract_json(raw) if raw else None
        if parsed:
            message = str(parsed.get("message") or "").strip()
            if message:
                base["message"] = message
    return base


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def generate_artifact(
    artifact_type: str, rec: Dict[str, Any], account: Dict[str, Any]
) -> Dict[str, Any]:
    """Dispatch to the right generator. Raises ValueError on unknown types."""

    if artifact_type == "email":
        return draft_email(rec, account)
    if artifact_type == "crm_task":
        return create_crm_task(rec, account)
    if artifact_type == "slack":
        return slack_handoff(rec, account)
    raise ValueError(
        f"unknown artifact_type '{artifact_type}'; expected one of {list(ARTIFACT_TYPES)}"
    )
