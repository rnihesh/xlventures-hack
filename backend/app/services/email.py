"""Email delivery via AWS SES, offline-safe.

The only public entry point is :func:`send_verification`, which mails a signup
verification link. It is deliberately defensive: when AWS credentials are
absent, the sender is unconfigured, or SES rejects the request, it returns a
``{'sent': False, 'reason': ...}`` result instead of raising. This keeps the
auth flow working in development and tests (where it auto-verifies and logs the
link) without ever taking the API down because email could not be sent.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger("app.services.email")

# A pragmatic email shape check. The point is to reject obvious non-addresses
# (a contact NAME like "Marcus Reyes", or a value with stray whitespace/control
# characters) before they reach SES, which would otherwise fail with an opaque
# "Local address contains control or whitespace" error.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Placeholder / example domains an assistant tends to FABRICATE when it does not
# have a real contact (e.g. "nihesh@yourcompany.com"). Sending to these is always
# wrong, so we reject them outright: a recipient must be a real saved contact or
# an address the user actually gave, never an invented one.
_FAKE_DOMAINS = {
    "yourcompany.com", "company.com", "mycompany.com", "yourdomain.com",
    "domain.com", "example.com", "example.org", "example.net", "email.com",
    "test.com", "sample.com", "placeholder.com",
    "company.co", "yourcompany.co", "noemail.com", "none.com",
}


def is_valid_email(addr: str | None) -> bool:
    """True when ``addr`` looks like a single, clean, non-placeholder address."""

    if not addr:
        return False
    candidate = addr.strip()
    if any(ord(c) < 32 for c in candidate):
        return False
    if not _EMAIL_RE.match(candidate):
        return False
    # Normalize (a trailing dot makes "yourcompany.com." bypass the set), and
    # reject the fake domain itself AND any subdomain of it.
    domain = candidate.rsplit("@", 1)[-1].lower().rstrip(".")
    if not domain or "." not in domain:
        return False
    return not any(domain == f or domain.endswith("." + f) for f in _FAKE_DOMAINS)


def _build_message(link: str) -> tuple[str, str, str]:
    """Return (subject, text body, html body) for the verification email."""

    from app.services.email_templates import (
        verification_html,
        verification_subject,
        verification_text,
    )

    return verification_subject(), verification_text(link), verification_html(link)


def send_verification(to: str, link: str) -> dict[str, Any]:
    """Send a verification email to ``to`` containing ``link``.

    Never raises. Returns a result dict describing what happened:

    * ``{'sent': True, 'message_id': ...}`` on a successful SES send;
    * ``{'sent': False, 'reason': ...}`` when SES is unavailable, the sender is
      not configured, credentials are missing, or the send failed. Callers in
      development treat a non-sent result as a signal to auto-verify and log the
      link so the flow still completes offline.
    """

    sender = settings.ses_sender_email
    if not sender:
        logger.info("SES sender not configured; skipping verification email")
        return {"sent": False, "reason": "ses_sender_not_configured", "link": link}

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except Exception as exc:  # noqa: BLE001 - boto3 missing is non-fatal
        logger.info("boto3 unavailable (%s); skipping verification email", exc)
        return {"sent": False, "reason": "boto3_unavailable", "link": link}

    subject, text_body, html_body = _build_message(link)

    try:
        client = boto3.client("ses", region_name=settings.aws_region)
        response = client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
        message_id = response.get("MessageId")
        logger.info("Sent verification email to %s (id=%s).", to, message_id)
        return {"sent": True, "message_id": message_id}
    except NoCredentialsError as exc:
        logger.info("No AWS credentials (%s); skipping verification email", exc)
        return {"sent": False, "reason": "no_aws_credentials", "link": link}
    except (ClientError, BotoCoreError) as exc:  # noqa: PERF203
        logger.warning("SES send failed (%s); skipping verification email", exc)
        return {"sent": False, "reason": f"ses_error: {exc}", "link": link}
    except Exception as exc:  # noqa: BLE001 - never let email take down auth
        logger.warning("Unexpected email error (%s)", exc)
        return {"sent": False, "reason": f"unexpected: {exc}", "link": link}


def send_email(
    to: str,
    subject: str,
    body: str,
    sender: str | None = None,
) -> dict[str, Any]:
    """Send a plain-text email via AWS SES. Never raises.

    Used by the execute / send flow when a user clicks Send on an email
    artifact. ``sender`` defaults to the org's configured SES sender, falling
    back to ``settings.ses_sender_email``. Returns a result dict:

    * ``{'sent': True, 'message_id': ...}`` on a successful SES send;
    * ``{'sent': False, 'reason': 'ses_not_configured'}`` when no sender is set,
      AWS credentials are missing, or boto3 is unavailable;
    * ``{'sent': False, 'reason': ...}`` when SES rejects the request.
    """

    source = sender or settings.ses_sender_email
    if not source:
        logger.info("SES sender not configured; skipping email send")
        return {"sent": False, "reason": "ses_not_configured"}

    # Reject a non-address (e.g. a contact's name) before it reaches SES so the
    # caller gets a clear reason instead of an opaque SES whitespace error.
    if not is_valid_email(to):
        logger.info("Invalid email recipient %r; skipping send", to)
        return {"sent": False, "reason": "invalid_recipient", "detail": to}
    to = to.strip()

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except Exception as exc:  # noqa: BLE001 - boto3 missing is non-fatal
        logger.info("boto3 unavailable (%s); skipping email send", exc)
        return {"sent": False, "reason": "ses_not_configured"}

    from app.services.email_templates import outreach_html

    try:
        client = boto3.client("ses", region_name=settings.aws_region)
        response = client.send_email(
            Source=source,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body, "Charset": "UTF-8"},
                    "Html": {"Data": outreach_html(body), "Charset": "UTF-8"},
                },
            },
        )
        message_id = response.get("MessageId")
        logger.info("Sent email to %s (id=%s).", to, message_id)
        return {"sent": True, "message_id": message_id}
    except NoCredentialsError as exc:
        logger.info("No AWS credentials (%s); skipping email send", exc)
        return {"sent": False, "reason": "ses_not_configured"}
    except (ClientError, BotoCoreError) as exc:  # noqa: PERF203
        logger.warning("SES send failed (%s)", exc)
        return {"sent": False, "reason": f"ses_error: {exc}"}
    except Exception as exc:  # noqa: BLE001 - never let email take down the API
        logger.warning("Unexpected email error (%s)", exc)
        return {"sent": False, "reason": f"unexpected: {exc}"}
