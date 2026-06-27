"""Offline tests: send_artifact emails ALL of an account's saved contacts.

These prove the 'email the play to all contacts of <account>' behavior at the
chat tool layer, with the SES send mocked so nothing touches the network:

* it fans out to every saved contact of the account (resolved via
  ``contacts_repo.list_for_account``), skipping contacts without a valid email
  and never using the account owner name as an address;
* it returns ``reason='no_contacts'`` (and never attempts a send) when the
  account has no contacts, instead of guessing;
* it is org-scoped: org A's send never reaches org B's contacts, even when both
  orgs have contacts linked to the same account id.

Everything runs with a blank OPENAI_API_KEY (deterministic / offline path).
"""

from __future__ import annotations

import asyncio
import uuid

import app.services.email as email_mod
from app.chat import tools as toolkit
from app.repositories import contacts as contacts_repo

# A minimal inline recommendation: the artifact generators tolerate partial
# recommendations, so this is enough to render a template email offline.
_REC = {
    "action": {
        "title": "Renewal save play",
        "description": "Set up an executive review before renewal.",
    }
}


def _run(coro):
    return asyncio.run(coro)


def test_send_artifact_emails_all_account_contacts(monkeypatch) -> None:
    """Every saved contact of the account is emailed; invalid / other-account
    contacts are excluded and the owner name is never used as an address."""

    captured: list[str] = []

    def _fake_send_email(to, subject, body, sender=None):  # noqa: ANN001
        captured.append(to)
        return {"sent": True, "message_id": f"m-{to}"}

    monkeypatch.setattr(email_mod, "send_email", _fake_send_email)

    org = f"org_{uuid.uuid4().hex[:6]}"
    account_id = "ACC-7001"

    async def go():
        toolkit.set_current_org(org)
        await contacts_repo.upsert(org, "Dana Lee", "dana@acme.com", account_id=account_id)
        await contacts_repo.upsert(org, "Sam Ray", "sam@acme.com", account_id=account_id)
        # No valid email: must be skipped, never sent to.
        await contacts_repo.upsert(org, "No Email", "", account_id=account_id)
        # A different account's contact: must not be included.
        await contacts_repo.upsert(org, "Other", "other@acme.com", account_id="ACC-9999")
        return await toolkit.send_artifact(
            channel="email",
            recommendation=_REC,
            account_id=account_id,
            all_account_contacts=True,
        )

    out = _run(go())

    assert out.get("sent") is True
    assert set(captured) == {"dana@acme.com", "sam@acme.com"}
    # The account owner name is never used: only real addresses are sent to.
    assert all("@" in addr for addr in captured)


def test_send_artifact_no_contacts_returns_no_contacts(monkeypatch) -> None:
    """An account with no contacts yields reason 'no_contacts' and sends nothing."""

    attempted: list[str] = []

    def _fake_send_email(to, subject, body, sender=None):  # noqa: ANN001
        attempted.append(to)
        return {"sent": True}

    monkeypatch.setattr(email_mod, "send_email", _fake_send_email)

    org = f"org_{uuid.uuid4().hex[:6]}"

    async def go():
        toolkit.set_current_org(org)
        return await toolkit.send_artifact(
            channel="email",
            recommendation=_REC,
            account_id="ACC-EMPTY",
            all_account_contacts=True,
        )

    out = _run(go())

    assert out.get("sent") is False
    assert out.get("reason") == "no_contacts"
    assert attempted == []


def test_send_artifact_contacts_org_scoped(monkeypatch) -> None:
    """Org A never emails org B's contacts, even on the same account id."""

    captured: list[str] = []

    def _fake_send_email(to, subject, body, sender=None):  # noqa: ANN001
        captured.append(to)
        return {"sent": True, "message_id": "x"}

    monkeypatch.setattr(email_mod, "send_email", _fake_send_email)

    org_a = f"orgA_{uuid.uuid4().hex[:6]}"
    org_b = f"orgB_{uuid.uuid4().hex[:6]}"
    account_id = "ACC-SHARED"

    async def go():
        # Org B has a contact linked to the shared account id.
        await contacts_repo.upsert(org_b, "B Person", "b@orgb.com", account_id=account_id)
        # Org A has its own contact on the same account id.
        await contacts_repo.upsert(org_a, "A Person", "a@orga.com", account_id=account_id)
        # The send runs as org A.
        toolkit.set_current_org(org_a)
        return await toolkit.send_artifact(
            channel="email",
            recommendation=_REC,
            account_id=account_id,
            all_account_contacts=True,
        )

    out = _run(go())

    assert out.get("sent") is True
    assert captured == ["a@orga.com"]
    assert "b@orgb.com" not in captured
