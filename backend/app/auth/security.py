"""Password hashing (bcrypt) and session tokens (JWT, HS256).

Kept dependency-light: bcrypt directly for passwords and PyJWT for the session
cookie. The JWT carries the user id and org id plus standard expiry claims so
the auth dependencies can rebuild the current principal without a DB lookup on
every request (a lookup still confirms the user exists).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import bcrypt
import jwt

from app.config import settings

# Cookie used to carry the session JWT.
SESSION_COOKIE = "nba_session"
# Session lifetime: 7 days, per spec.
SESSION_TTL = dt.timedelta(days=7)
_ALGORITHM = "HS256"

# bcrypt rejects passwords longer than 72 bytes; we pre-truncate defensively.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password`` as a UTF-8 string."""

    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True when ``password`` matches the stored bcrypt ``password_hash``."""

    if not password_hash:
        return False
    try:
        pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_session_token(user_id: str, org_id: str) -> str:
    """Encode a signed session JWT carrying the user and org ids."""

    now = dt.datetime.now(tz=dt.UTC)
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "org_id": org_id,
        "iat": now,
        "exp": now + SESSION_TTL,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_session_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a session JWT, returning its claims or None.

    Returns None for any invalid, expired, or malformed token so callers can
    treat a bad cookie exactly like a missing one (401).
    """

    if not token:
        return None
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
