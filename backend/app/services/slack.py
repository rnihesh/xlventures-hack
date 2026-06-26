"""Slack delivery via incoming webhooks, offline-safe.

The only public entry point is :func:`post_message`, which POSTs a text message
to a Slack incoming-webhook URL. It is deliberately defensive: when no webhook
is configured, httpx is unavailable, or Slack rejects the request, it returns a
``{'sent': False, 'reason': ...}`` result instead of raising. This keeps the
execute / send flow working in development and tests (no network) without ever
taking the API down because Slack could not be reached.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app.services.slack")


def post_message(webhook_url: str | None, text: str) -> dict[str, Any]:
    """Post ``text`` to a Slack incoming webhook. Never raises.

    Returns a result dict describing what happened:

    * ``{'sent': True}`` when Slack accepts the message;
    * ``{'sent': False, 'reason': ...}`` when no webhook is configured, httpx is
      unavailable, or the POST failed.
    """

    if not webhook_url:
        logger.info("Slack webhook not configured; skipping message")
        return {"sent": False, "reason": "slack_not_configured"}

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001 - httpx missing is non-fatal
        logger.info("httpx unavailable (%s); skipping Slack message", exc)
        return {"sent": False, "reason": "httpx_unavailable"}

    try:
        response = httpx.post(webhook_url, json={"text": text}, timeout=10.0)
    except Exception as exc:  # noqa: BLE001 - never let Slack take down the API
        logger.warning("Slack post failed (%s)", exc)
        return {"sent": False, "reason": f"slack_error: {exc}"}

    if response.status_code >= 400:
        logger.warning(
            "Slack webhook returned %s: %s", response.status_code, response.text
        )
        return {
            "sent": False,
            "reason": f"slack_http_{response.status_code}",
            "detail": response.text,
        }

    logger.info("Posted Slack message via webhook.")
    return {"sent": True}
