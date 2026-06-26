"""Offline tests for the agentic chatbot.

Every assertion holds with no OPENAI_API_KEY and no DATABASE_URL: the agent
takes its deterministic intent-router path over the shared tool layer. These
prove the chat is fully functional offline end to end (router -> tool -> answer)
both at the agent layer and through the HTTP endpoints.
"""

from __future__ import annotations

import asyncio

from app.chat import agent as chat_agent
from app.chat import tools as toolkit


def _final(events):
    for event in events:
        if event["type"] == "final":
            return event
    raise AssertionError("no final event emitted")


def test_router_riskiest_accounts_calls_list_accounts() -> None:
    """'show me the riskiest accounts' routes to list_accounts and returns them."""

    async def run():
        return [
            e
            async for e in chat_agent.stream(
                [{"role": "user", "content": "show me the riskiest accounts"}]
            )
        ]

    events = asyncio.run(run())
    tool_calls = [e for e in events if e["type"] == "tool.called"]
    assert tool_calls and tool_calls[0]["data"]["tool"] == "list_accounts"

    final = _final(events)
    # The composed answer lists real seeded accounts.
    assert "accounts by risk" in final["data"]["content"]
    assert any(t["tool"] == "list_accounts" for t in final["data"]["trace"])


def test_router_domains_calls_list_domains() -> None:
    """'what domains are available' routes to list_domains and lists the packs."""

    async def run():
        return await chat_agent.answer(
            [{"role": "user", "content": "what domains are available?"}]
        )

    result = asyncio.run(run())
    assert any(t["tool"] == "list_domains" for t in result["trace"])
    # All three seeded verticals are surfaced in the answer.
    for key in ("customer_success", "saas_sales", "collections"):
        assert key in result["answer"]


def test_chat_endpoint_returns_answer_and_trace(client) -> None:
    """POST /chat answers offline and returns a tool trace."""

    resp = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "what domains are available?"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"]
    assert any(t["tool"] == "list_domains" for t in body["trace"])


def test_chat_run_nba_offline(client) -> None:
    """A 'what should we do for ACC-1001' message runs the NBA pipeline offline."""

    resp = client.post(
        "/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "what should we do for ACC-1001? usage dropped sharply",
                }
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(t["tool"] == "run_nba" for t in body["trace"])
    assert body["answer"]


def test_send_artifact_email_routes_via_ses() -> None:
    """Emailing a last run routes to send_artifact. Email always uses SES (no
    connector), so it must NOT tell the user to connect email in Settings."""

    async def run():
        await chat_agent.answer(
            [{"role": "user", "content": "what should we do for ACC-1001? usage dropped"}]
        )
        return await chat_agent.answer(
            [
                {
                    "role": "user",
                    "content": "email the recommendation from my last run to ops@acme.test",
                }
            ]
        )

    result = asyncio.run(run())
    assert any(t["tool"] == "send_artifact" for t in result["trace"])
    # Email never claims it needs connecting in Settings (only Slack does).
    assert "connect" not in result["answer"].lower() or "slack" in result["answer"].lower()


def test_send_named_account_to_slack_routes_to_send_artifact() -> None:
    """'send the Northwind play to slack' resolves the account name and refuses gracefully."""

    async def run():
        return await chat_agent.answer(
            [{"role": "user", "content": "send the Northwind play to slack"}]
        )

    result = asyncio.run(run())
    assert any(t["tool"] == "send_artifact" for t in result["trace"])


def test_get_last_run_and_tag_run_offline() -> None:
    """A run is retrievable as the org's last run and can be tagged."""

    async def run():
        await chat_agent.answer(
            [{"role": "user", "content": "what should we do for ACC-1001? usage dropped"}]
        )
        last = await toolkit.run_tool("get_last_run", {})
        tagged = await chat_agent.answer(
            [{"role": "user", "content": "tag this run with account ACC-1001"}]
        )
        return last, tagged

    last, tagged = asyncio.run(run())
    assert last.get("found") and last.get("recommendation")
    assert last.get("account_id") == "ACC-1001"
    assert any(t["tool"] == "tag_run" for t in tagged["trace"])


def test_recommend_phrasing_still_runs_nba_not_send() -> None:
    """'what do we recommend for ACC-1001' runs the NBA pipeline, not a send."""

    async def run():
        return await chat_agent.answer(
            [{"role": "user", "content": "what do we recommend for ACC-1001?"}]
        )

    result = asyncio.run(run())
    tool_names = [t["tool"] for t in result["trace"]]
    assert "run_nba" in tool_names
    assert "send_artifact" not in tool_names
