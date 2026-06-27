"""Shared pytest fixtures.

Guarantees the whole suite runs offline and deterministically:

* clears OPENAI_API_KEY, DATABASE_URL, and APP_TOKEN before the app is built,
  so the LLM, database, and auth layers all take their offline code paths;
* exposes a FastAPI TestClient bound to ``app.main:app`` for the API tests.

The TestClient drives the app through its real lifespan (startup/shutdown),
which best-effort initializes a DB pool (None offline) and an in-memory
LangGraph checkpointer, exactly as in production minus the external services.
"""

from __future__ import annotations

import os

import pytest

# Force the offline configuration before any app module that reads the
# environment (config.settings) is imported by a fixture or test. We clear every
# credential that would make a test hit a network or change a code path (AWS/SES
# so signup auto-verifies offline, Google so OAuth/integrations read "not
# configured"), so the suite is hermetic even if a real .env or shell env is
# present.
for _var in (
    "OPENAI_API_KEY",
    "DATABASE_URL",
    "APP_TOKEN",
    "LANGSMITH_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "SES_SENDER_EMAIL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "SLACK_WEBHOOK_URL",
):
    os.environ.pop(_var, None)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEMO_MODE", "1")


@pytest.fixture(scope="session")
def app():
    """Return the FastAPI application instance, built offline."""

    from app.main import app as fastapi_app

    return fastapi_app


@pytest.fixture()
def client(app):
    """A FastAPI TestClient, logged in as the Demo user, running offline.

    Using the client as a context manager triggers startup and shutdown so the
    in-memory checkpointer and (absent) DB pool are wired exactly as at runtime.
    User-facing endpoints are org-scoped, so the fixture logs in as the seeded
    Demo user (which owns all seed data); the session cookie persists on the
    client for every subsequent request.
    """

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        resp = test_client.post(
            "/auth/login",
            json={"email": "demo@niheshr.com", "password": "demo1234"},
        )
        assert resp.status_code == 200, f"demo login failed: {resp.text}"
        yield test_client
