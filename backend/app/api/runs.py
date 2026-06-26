"""Run lifecycle API: create, stream (SSE), and human in the loop decisions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.deps import get_checkpointer
from app.graph.planner import build_graph

router = APIRouter(tags=["runs"])

# In memory run registry for the walking skeleton.
_RUNS: Dict[str, Dict[str, Any]] = {}

EVENT_TYPES = {
    "run.started",
    "node.started",
    "node.finished",
    "token",
    "recommendation",
    "hitl.required",
    "run.finished",
    "error",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SignalIn(BaseModel):
    type: str
    content: str


class CreateRunIn(BaseModel):
    domain: str
    account_id: str
    signal: SignalIn


class CreateRunOut(BaseModel):
    run_id: str


class HitlIn(BaseModel):
    decision: str = Field(..., description="approve | reject | edit")
    edited_action: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


def _envelope(run_id: str, seq: int, event_type: str, data: Dict[str, Any]) -> Dict[str, str]:
    """Build an SSE payload that matches contracts/events.schema.json.

    Returned as a dict whose single ``data`` field is the JSON envelope, so
    sse-starlette emits exactly ``data: <json>\\n\\n``.
    """

    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    payload = {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "seq": seq,
        "type": event_type,
        "ts": _now_iso(),
        "data": data,
    }
    return {"data": json.dumps(payload)}


@router.post("/runs", response_model=CreateRunOut)
async def create_run(body: CreateRunIn) -> CreateRunOut:
    """Create a run, store its minimal record, and return its id."""

    run_id = str(uuid.uuid4())
    _RUNS[run_id] = {
        "run_id": run_id,
        "domain": body.domain,
        "account_id": body.account_id,
        "signal": body.signal.model_dump(),
        "status": "created",
        "recommendation": None,
        "hitl": None,
        "created_at": _now_iso(),
    }
    return CreateRunOut(run_id=run_id)


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> EventSourceResponse:
    """Stream the graph execution as Server Sent Events."""

    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def event_generator() -> AsyncIterator[Dict[str, str]]:
        seq = 0
        run["status"] = "running"

        yield _envelope(
            run_id,
            seq,
            "run.started",
            {"domain": run["domain"], "account_id": run["account_id"]},
        )
        seq += 1

        initial_state = {
            "run_id": run_id,
            "domain": run["domain"],
            "account_id": run["account_id"],
            "signal": run["signal"],
            "plan": [],
            "steps": [],
            "messages": [],
            "recommendation": None,
        }
        config = {"configurable": {"thread_id": run_id}}

        try:
            checkpointer = get_checkpointer()
            graph = build_graph(checkpointer)

            async for chunk in graph.astream(
                initial_state, config=config, stream_mode="updates"
            ):
                for node_name, update in chunk.items():
                    yield _envelope(
                        run_id, seq, "node.started", {"node": node_name}
                    )
                    seq += 1

                    update = update or {}
                    finished_data: Dict[str, Any] = {"node": node_name}
                    steps = update.get("steps") or []
                    if steps:
                        finished_data["summary"] = steps[-1].get("summary", "")
                    yield _envelope(
                        run_id, seq, "node.finished", finished_data
                    )
                    seq += 1

                    recommendation = update.get("recommendation")
                    if recommendation:
                        run["recommendation"] = recommendation
                        yield _envelope(
                            run_id, seq, "recommendation", recommendation
                        )
                        seq += 1

                    critic = update.get("critic")
                    if critic and critic.get("requires_hitl"):
                        yield _envelope(
                            run_id,
                            seq,
                            "hitl.required",
                            {
                                "reason": "High risk action requires approval.",
                                "recommendation_id": (run.get("recommendation") or {}).get("id"),
                            },
                        )
                        seq += 1

            run["status"] = "finished"
            yield _envelope(
                run_id,
                seq,
                "run.finished",
                {
                    "status": "finished",
                    "has_recommendation": run.get("recommendation") is not None,
                },
            )
            seq += 1
        except Exception as exc:  # noqa: BLE001 - surface failure to the client stream
            run["status"] = "error"
            yield _envelope(run_id, seq, "error", {"message": str(exc)})

    return EventSourceResponse(event_generator())


@router.post("/runs/{run_id}/hitl")
async def hitl(run_id: str, body: HitlIn) -> Dict[str, str]:
    """Record a human in the loop decision for a run."""

    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if body.decision not in {"approve", "reject", "edit"}:
        raise HTTPException(status_code=422, detail="invalid decision")

    run["hitl"] = {
        "decision": body.decision,
        "edited_action": body.edited_action,
        "reason": body.reason,
        "recorded_at": _now_iso(),
    }

    recommendation = run.get("recommendation")
    if recommendation:
        status_map = {"approve": "approved", "reject": "rejected", "edit": "edited"}
        recommendation["status"] = status_map[body.decision]
        if body.decision == "edit" and body.edited_action:
            recommendation["action"] = {**recommendation["action"], **body.edited_action}

    return {"status": "recorded"}
