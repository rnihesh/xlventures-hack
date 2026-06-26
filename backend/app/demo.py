"""Deterministic DEMO MODE support.

This module exists so live demos never flake: it provides a fully offline,
reproducible fake chat model plus small helpers for stable ids and timestamps.
Nothing here touches the network, and every output is a pure function of its
input, so a run with ``DEMO_MODE`` enabled always produces the same on-topic
text for the planner, recommender, drafter, and critic prompts.

The fake model is LangChain compatible: it subclasses ``BaseChatModel`` and
returns an ``AIMessage`` from ``invoke`` just like ``ChatOpenAI`` would. Callers
read ``result.content`` and never know the difference.
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.config import settings

# ---------------------------------------------------------------------------
# Demo-mode detection and stable id/timestamp helpers
# ---------------------------------------------------------------------------

# A fixed point in time used for every demo timestamp so runs are byte-for-byte
# reproducible. Chosen as a neutral, unambiguous UTC instant.
DEMO_EPOCH = "2026-01-01T00:00:00+00:00"

# A stable namespace so ``stable_uuid`` is reproducible across processes.
_DEMO_NAMESPACE = uuid.UUID("0d15ea5e-0000-4000-8000-000000000000")

# Values that count as "truthy" for the DEMO_MODE environment variable.
_TRUTHY = {"1", "true", "yes", "on", "y", "t"}


def _env_demo_flag() -> bool:
    """True when the ``DEMO_MODE`` environment variable is set to a truthy value."""

    return os.environ.get("DEMO_MODE", "").strip().lower() in _TRUTHY


def demo_mode_enabled() -> bool:
    """Return whether deterministic demo mode should be active.

    Demo mode is on when ``DEMO_MODE`` is truthy OR when there is no configured
    OpenAI API key. The second clause means running offline is automatically
    deterministic: with no key there is nothing real to call, so the canned model
    keeps the engine fully functional instead of failing on the network.
    """

    return _env_demo_flag() or not bool(settings.openai_api_key)


def stable_uuid(seed: str) -> str:
    """Return a deterministic UUID string derived from ``seed`` (uuid5)."""

    return str(uuid.uuid5(_DEMO_NAMESPACE, str(seed)))


def stable_timestamp() -> str:
    """Return a fixed ISO-8601 timestamp for reproducible demo output."""

    return DEMO_EPOCH


# ---------------------------------------------------------------------------
# Canned, on-topic responses
# ---------------------------------------------------------------------------

# The ordered plan the planner expects, one specialist per line. Mirrors the
# real pipeline so the planner's newline parsing produces a sensible plan.
_PLANNER_PLAN = "\n".join(
    [
        "Run retrieval",
        "Run risk scorer",
        "Run play recommender",
        "Run outcome simulator",
        "Run drafter",
        "Run critic",
    ]
)

# A warm, placeholder-free outreach email body (used by the drafter's free-text
# email path).
_EMAIL_BODY = (
    "Hi there,\n\n"
    "I have been reviewing how things are tracking on your account and want to "
    "make sure we keep delivering the outcomes you signed up for. I would like to "
    "propose a short executive business review this week so we can realign on your "
    "goals, walk through recent usage, and agree on clear next steps ahead of "
    "renewal.\n\n"
    "Are you open to 30 minutes? I will come prepared with a tailored plan.\n\n"
    "Best,\nYour Customer Success team"
)

# Strict-JSON variants for the artifact generators (subject/body, title/notes,
# slack message). Returned verbatim so the generators' JSON extraction succeeds.
_EMAIL_JSON = (
    '{"subject": "Quick proposal: realign before renewal", '
    '"body": "Hi there,\\n\\nI have been reviewing how things are tracking on your '
    "account and want to keep delivering the outcomes you signed up for. Could we "
    "hold a short executive business review this week to realign on goals and lock "
    "in next steps before renewal?\\n\\nHappy to send a tailored agenda in advance.\\n\\n"
    'Best,\\nYour Customer Success team"}'
)

_CRM_JSON = (
    '{"title": "Schedule executive business review", '
    '"notes": "Usage has dipped ahead of renewal and sponsor engagement has '
    "lapsed. Book a strategic review with the buying committee to realign on value "
    'and protect the renewal."}'
)

_SLACK_JSON = (
    '{"message": ":handshake: *Account handoff* \\n> Usage dipped ahead of renewal '
    "and the sponsor has gone quiet.\\n*Recommended play:* Schedule an executive "
    "business review\\nReact with :white_check_mark: to take it, or reply to "
    'discuss."}'
)


def _prompt_text(messages: List[BaseMessage]) -> str:
    """Flatten a list of chat messages into a single prompt string."""

    parts: List[str] = []
    for message in messages:
        content = getattr(message, "content", message)
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            # Multi-part content: keep only the string fragments.
            parts.extend(str(p) for p in content if isinstance(p, str))
        else:
            parts.append(str(content))
    return "\n".join(parts)


def _rationale_response(prompt: str) -> str:
    """Build a deterministic two-sentence rationale tailored to the prompt."""

    action = "the recommended play"
    account = "this account"
    match = re.search(r"'(.+?)' is the next best action for account (\S+?)[\.\s]", prompt)
    if match:
        action = match.group(1).strip()
        account = match.group(2).strip().rstrip(".")

    return (
        f"{action} is the next best action for account {account} because the "
        "evidence shows usage declining sharply while executive sponsor engagement "
        "has lapsed inside the renewal window. Acting now re-anchors value with the "
        "decision makers before the risk compounds, which the cited usage and CRM "
        "signals make the clear, highest-impact move."
    )


def canned_response(prompt: str) -> str:
    """Return an on-topic, deterministic response for a given prompt.

    Routing is keyword based and ordered most-specific first so each agent
    (planner, recommender/critic rationale, drafter, artifact generators) gets a
    correctly shaped answer.
    """

    lowered = prompt.lower()

    # Strict-JSON artifact generators (most specific: require both markers).
    if "strict json" in lowered:
        if '"subject"' in prompt and '"body"' in prompt:
            return _EMAIL_JSON
        if '"title"' in prompt and '"notes"' in prompt:
            return _CRM_JSON
        if '"message"' in prompt:
            return _SLACK_JSON

    # Verbalized rationale used by the recommendation builder / critic.
    if "next best action" in lowered and "explain why" in lowered:
        return _rationale_response(prompt)

    # Planner: ordered specialist steps as a newline-separated list.
    if "specialist steps" in lowered or "newline separated list" in lowered:
        return _PLANNER_PLAN

    # Free-text outreach email (drafter path, no JSON requested).
    if "outreach email" in lowered:
        return _EMAIL_BODY

    # Generic, safe, on-topic fallback so nothing ever returns empty.
    return (
        "Recommend scheduling an executive business review to realign on value "
        "and protect the renewal, grounded in the cited usage and engagement "
        "signals."
    )


# ---------------------------------------------------------------------------
# LangChain-compatible fake chat model
# ---------------------------------------------------------------------------


class DemoChatModel(BaseChatModel):
    """A deterministic, offline chat model used for live demos and tests.

    It mimics ``ChatOpenAI`` closely enough for this app: ``invoke`` returns an
    ``AIMessage`` whose ``content`` is a canned, on-topic string selected from
    the prompt. It accepts and ignores any constructor kwargs (model, api_key,
    temperature, streaming, base_url, ...) so it is a drop-in replacement.
    """

    def __init__(self, **kwargs: Any) -> None:  # noqa: D401 - swallow LLM kwargs
        # Ignore every provider-specific kwarg; the demo model is configless.
        super().__init__()

    @property
    def _llm_type(self) -> str:
        return "demo-chat-model"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = canned_response(_prompt_text(messages))
        message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Pure and synchronous-safe: reuse the deterministic sync path.
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def get_demo_llm(model: str | None = None, **kwargs: Any) -> DemoChatModel:
    """Return a configured :class:`DemoChatModel` (kwargs are ignored)."""

    return DemoChatModel(model=model, **kwargs)
