"""Google OAuth + Gmail send helpers, offline-safe.

Three entry points back the Google connector:

* :func:`consent_url`   -> build the Google consent URL from GOOGLE_CLIENT_ID +
                           GOOGLE_REDIRECT_URI (pure string building, no network).
* :func:`exchange_code` -> trade an authorization ``code`` for access / refresh
                           tokens via the Google token endpoint.
* :func:`refresh`       -> mint a fresh access token from a stored refresh token.
* :func:`send_gmail`    -> best-effort send a message through the Gmail API with
                           a stored access token.

Every network call is defensive: missing config, an unavailable httpx, or a
failed request yields a ``{'sent': False, ...}`` / ``{'ok': False, ...}`` result
rather than an exception, so the integrations and execute flows stay up offline.
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from app.config import settings

logger = logging.getLogger("app.services.google_oauth")

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GMAIL_SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"

# Scopes: send mail and read the connected account's email address.
_SCOPES = "openid email profile"


def is_configured() -> bool:
    """True when the Google client id + secret are both set."""

    return bool(settings.google_client_id and settings.google_client_secret)


def consent_url(state: str | None = None) -> Optional[str]:
    """Return the Google consent URL, or None when the client id is unset.

    Pure string building (no network), so it is always safe to call.
    """

    if not settings.google_client_id:
        return None
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    if state:
        params["state"] = state
    return f"{_AUTH_ENDPOINT}?{urlencode(params)}"


def _expiry_iso(expires_in: Any) -> Optional[str]:
    """Turn a Google ``expires_in`` (seconds) into an absolute ISO timestamp."""

    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _fetch_email(access_token: str) -> Optional[str]:
    """Best-effort lookup of the connected account's email address."""

    try:
        import httpx

        resp = httpx.get(
            _USERINFO,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        if resp.status_code < 400:
            data = resp.json()
            # Only trust the email when Google reports it verified. An unverified
            # Google email must never resolve an account, else an attacker who
            # added a victim's address to their own Google account (without
            # verifying it) could sign in as the victim.
            if data.get("verified_email") is True:
                return data.get("email")
            logger.info("Google email present but not verified; rejecting")
    except Exception as exc:  # noqa: BLE001 - email is best-effort metadata
        logger.info("Could not fetch Google userinfo (%s)", exc)
    return None


def exchange_code(code: str) -> Dict[str, Any]:
    """Exchange an authorization ``code`` for tokens. Never raises.

    Returns ``{'ok': True, 'tokens': {...}}`` on success where ``tokens`` carries
    ``access_token``, ``refresh_token``, ``expiry``, and ``email``; otherwise
    ``{'ok': False, 'reason': ...}``.
    """

    if not is_configured():
        return {"ok": False, "reason": "google_not_configured"}
    if not code:
        return {"ok": False, "reason": "missing_code"}

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        logger.info("httpx unavailable (%s); cannot exchange Google code", exc)
        return {"ok": False, "reason": "httpx_unavailable"}

    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        resp = httpx.post(_TOKEN_ENDPOINT, data=data, timeout=15.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google token exchange failed (%s)", exc)
        return {"ok": False, "reason": f"google_error: {exc}"}

    if resp.status_code >= 400:
        logger.warning("Google token exchange %s: %s", resp.status_code, resp.text)
        return {"ok": False, "reason": f"google_http_{resp.status_code}", "detail": resp.text}

    payload = resp.json()
    access_token = payload.get("access_token")
    tokens = {
        "access_token": access_token,
        "refresh_token": payload.get("refresh_token"),
        "expiry": _expiry_iso(payload.get("expires_in")),
        "email": _fetch_email(access_token) if access_token else None,
    }
    return {"ok": True, "tokens": tokens}


def refresh(refresh_token: str | None) -> Dict[str, Any]:
    """Mint a fresh access token from a refresh token. Never raises."""

    if not is_configured():
        return {"ok": False, "reason": "google_not_configured"}
    if not refresh_token:
        return {"ok": False, "reason": "google_not_connected"}

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        logger.info("httpx unavailable (%s); cannot refresh Google token", exc)
        return {"ok": False, "reason": "httpx_unavailable"}

    data = {
        "refresh_token": refresh_token,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "grant_type": "refresh_token",
    }
    try:
        resp = httpx.post(_TOKEN_ENDPOINT, data=data, timeout=15.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google token refresh failed (%s)", exc)
        return {"ok": False, "reason": f"google_error: {exc}"}

    if resp.status_code >= 400:
        return {"ok": False, "reason": f"google_http_{resp.status_code}", "detail": resp.text}

    payload = resp.json()
    return {
        "ok": True,
        "tokens": {
            "access_token": payload.get("access_token"),
            "expiry": _expiry_iso(payload.get("expires_in")),
        },
    }


def _raw_message(to: str, subject: str, body: str, sender: str | None) -> str:
    """Build a base64url-encoded RFC 2822 message for the Gmail API."""

    lines = [f"To: {to}", f"Subject: {subject}"]
    if sender:
        lines.insert(0, f"From: {sender}")
    lines.append("Content-Type: text/plain; charset=UTF-8")
    lines.append("")
    lines.append(body)
    raw = "\r\n".join(lines).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def send_gmail(
    connector: Optional[Dict[str, Any]],
    to: str,
    subject: str,
    body: str,
) -> Dict[str, Any]:
    """Send an email through the Gmail API using a stored Google connector.

    ``connector`` is the org's google connector record (``{'config': {...}}``).
    Never raises. Absent or expired credentials yield
    ``{'sent': False, 'reason': 'google_not_connected'}``.
    """

    config = (connector or {}).get("config") or {}
    access_token = config.get("access_token")

    # Try a refresh when there is no access token but a refresh token exists.
    if not access_token and config.get("refresh_token"):
        refreshed = refresh(config.get("refresh_token"))
        if refreshed.get("ok"):
            access_token = (refreshed.get("tokens") or {}).get("access_token")

    if not access_token:
        return {"sent": False, "reason": "google_not_connected"}

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        logger.info("httpx unavailable (%s); skipping Gmail send", exc)
        return {"sent": False, "reason": "httpx_unavailable"}

    sender = config.get("email")
    raw = _raw_message(to, subject, body, sender)
    try:
        resp = httpx.post(
            _GMAIL_SEND,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
            timeout=15.0,
        )
    except Exception as exc:  # noqa: BLE001 - never let Gmail take down the API
        logger.warning("Gmail send failed (%s)", exc)
        return {"sent": False, "reason": f"google_error: {exc}"}

    if resp.status_code == 401:
        return {"sent": False, "reason": "google_not_connected", "detail": "token expired"}
    if resp.status_code >= 400:
        return {"sent": False, "reason": f"google_http_{resp.status_code}", "detail": resp.text}

    message_id = None
    try:
        message_id = resp.json().get("id")
    except Exception:  # noqa: BLE001
        pass
    return {"sent": True, "message_id": message_id}
