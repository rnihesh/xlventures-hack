"""Chat API: a generic agentic chatbot over the whole platform.

Two endpoints share one agent (``app.chat.agent``):

* ``POST /chat/stream`` streams the agent's work as Server Sent Events using the
  same envelope style as the runs API: a monotonic ``seq`` and a typed payload.
  Event types: ``message`` (answer text), ``tool.called`` ({tool, args}),
  ``tool.result`` ({tool, summary}), ``thinking`` ({text?}: a lightweight
  reasoning pulse emitted when the agent starts and between tool calls, carrying
  the model's reasoning summary when it exposes one), and a final ``message``
  carrying the full answer and the tool trace. The event stream is additive: new
  event types (like ``thinking``) and fields may be added, never removed.

* ``POST /chat`` runs the agent to completion and returns the final answer plus
  the tool trace in one JSON response.

Both work fully offline: with no OpenAI key the agent uses a deterministic intent
router over the same tool layer, so the chat is functional and testable without
a network or database.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.api._org import current_org
from app.api.runs import require_auth
from app.chat import agent as chat_agent

# Single-tenant: the access boundary is the shared APP_TOKEN bearer (require_auth),
# applied to every chat endpoint here so they match the runs API. There are no
# per-user accounts, so all sessions belong to the one operator; multi-tenant use
# would add a user_id column and scope each query by the authenticated principal.
router = APIRouter(tags=["chat"], dependencies=[Depends(require_auth)])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatMessage(BaseModel):
    role: str = Field(description="user | assistant | system")
    content: str = Field(default="")


class ChatIn(BaseModel):
    """Body for the chat endpoints."""

    messages: List[ChatMessage] = Field(default_factory=list)
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional hints (account_id, domain, run_id, recommendation).",
    )


class ChatOut(BaseModel):
    answer: str
    trace: List[Dict[str, Any]]


def _envelope(seq: int, event_type: str, data: Dict[str, Any]) -> Dict[str, str]:
    """Build an SSE payload mirroring the runs API envelope style."""

    payload = {
        "id": str(uuid.uuid4()),
        "seq": seq,
        "type": event_type,
        "ts": _now_iso(),
        "data": data,
    }
    return {"data": json.dumps(payload, default=str)}


@router.post("/chat/stream")
async def chat_stream(
    body: ChatIn, org_id: str = Depends(current_org)
) -> EventSourceResponse:
    """Stream the agent's tokens, tool calls, and final answer as SSE."""

    messages = [m.model_dump() for m in body.messages]

    async def event_generator() -> AsyncIterator[Dict[str, str]]:
        seq = 0
        yield _envelope(seq, "chat.started", {"messages": len(messages)})
        seq += 1
        try:
            # Pass the authenticated org so every tool runs under THIS tenant,
            # never a client-supplied or default org.
            async for event in chat_agent.stream(messages, body.context, org_id=org_id):
                yield _envelope(seq, event["type"], event["data"])
                seq += 1
        except Exception:  # noqa: BLE001 - keep the stream contract intact
            yield _envelope(seq, "error", {"message": "internal error during chat"})

    return EventSourceResponse(event_generator())


@router.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, org_id: str = Depends(current_org)) -> ChatOut:
    """Run the agent to completion and return the final answer plus tool trace."""

    messages = [m.model_dump() for m in body.messages]
    result = await chat_agent.answer(messages, body.context, org_id=org_id)
    return ChatOut(answer=result["answer"], trace=result["trace"])


# ---------------------------------------------------------------------------
# Persisted chat sessions (multi-conversation history, stored in Postgres).
# ---------------------------------------------------------------------------

from fastapi import HTTPException  # noqa: E402

from app.repositories import chat_sessions as chat_repo  # noqa: E402


class SessionUpsert(BaseModel):
    title: str = Field(default="New chat")
    turns: List[Dict[str, Any]] = Field(default_factory=list)


@router.get("/chat/sessions")
async def list_chat_sessions(
    org_id: str = Depends(current_org),
) -> List[Dict[str, Any]]:
    """List the org's saved conversations (id, title, updated_at), newest first."""

    return await chat_repo.list_sessions(org_id)


@router.get("/chat/sessions/{session_id}")
async def get_chat_session(
    session_id: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Return one of the org's conversations with its full turns."""

    session = await chat_repo.get_session(session_id, org_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.put("/chat/sessions/{session_id}")
async def upsert_chat_session(
    session_id: str, body: SessionUpsert, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Create or update one of the org's conversations (title and turns)."""

    return await chat_repo.upsert_session(session_id, body.title, body.turns, org_id)


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(
    session_id: str, org_id: str = Depends(current_org)
) -> Dict[str, str]:
    """Delete one of the org's conversations."""

    await chat_repo.delete_session(session_id, org_id)
    return {"status": "deleted"}
