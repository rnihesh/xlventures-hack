"""Run lifecycle API: create, stream (SSE), and human in the loop decisions.

The stream endpoint drives the LangGraph planner and emits typed SSE events with
a monotonic ``seq``: run.started, node.started, node.finished, recommendation,
hitl.required, and run.finished. The HITL endpoint records the human decision,
writes the outcome back to memory against the run's episode, and triggers
distillation so the next similar run is measurably better.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from app.api._org import current_org
from app.deps import get_checkpointer
from app.graph.planner import build_graph

logger = logging.getLogger("app.api.runs")


def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    """Optional bearer-token gate.

    When APP_TOKEN is unset the API stays open (single-tenant demo mode). When
    it is set, every run endpoint requires ``Authorization: Bearer <APP_TOKEN>``.
    """

    expected = os.getenv("APP_TOKEN")
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="unauthorized")


router = APIRouter(tags=["runs"], dependencies=[Depends(require_auth)])

# In memory run registry. Durable run state lives in the LangGraph checkpointer;
# this registry holds the API-facing summary and the latest recommendation.
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


class EditedAction(BaseModel):
    """Whitelisted fields a human may override on the recommended action.

    extra='forbid' rejects any unexpected keys so a HITL edit cannot inject
    arbitrary fields into the recommendation's action object.
    """

    model_config = ConfigDict(extra="forbid")

    key: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


class HitlIn(BaseModel):
    decision: str = Field(..., description="approve | reject | edit")
    edited_action: Optional[EditedAction] = None
    reason: Optional[str] = None


def _envelope(run_id: str, seq: int, event_type: str, data: Dict[str, Any]) -> Dict[str, str]:
    """Build an SSE payload that matches contracts/events.schema.json."""

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
async def create_run(
    body: CreateRunIn, org_id: str = Depends(current_org)
) -> CreateRunOut:
    """Create a run scoped to the caller's org, store it, and return its id."""

    run_id = str(uuid.uuid4())
    _RUNS[run_id] = {
        "run_id": run_id,
        "org_id": org_id,
        "domain": body.domain,
        "account_id": body.account_id,
        "signal": body.signal.model_dump(),
        "status": "created",
        "recommendation": None,
        "episode_id": None,
        "hitl": None,
        "created_at": _now_iso(),
    }
    return CreateRunOut(run_id=run_id)


def _get_owned_run(run_id: str, org_id: str) -> Dict[str, Any]:
    """Fetch a run the caller's org owns, or 404 (never leak other orgs' runs)."""

    run = _RUNS.get(run_id)
    if run is None or run.get("org_id") != org_id:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str, org_id: str = Depends(current_org)
) -> EventSourceResponse:
    """Stream the graph execution as Server Sent Events."""

    run = _get_owned_run(run_id, org_id)

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
            "org_id": run.get("org_id"),
            "domain": run["domain"],
            "account_id": run["account_id"],
            "signal": run["signal"],
            "plan": [],
            "capabilities": [],
            "steps": [],
            "messages": [],
            "recommendation": None,
        }
        config = {"configurable": {"thread_id": run_id}}

        try:
            checkpointer = await get_checkpointer()
            graph = build_graph(checkpointer)

            async for chunk in graph.astream(
                initial_state, config=config, stream_mode="updates"
            ):
                for node_name, update in chunk.items():
                    yield _envelope(run_id, seq, "node.started", {"node": node_name})
                    seq += 1

                    update = update or {}
                    finished_data: Dict[str, Any] = {"node": node_name}
                    steps = update.get("steps") or []
                    if steps:
                        finished_data["summary"] = steps[-1].get("summary", "")
                        finished_data["data"] = steps[-1].get("data", {})
                    yield _envelope(run_id, seq, "node.finished", finished_data)
                    seq += 1

                    recommendation = update.get("recommendation")
                    if recommendation:
                        run["recommendation"] = recommendation
                        yield _envelope(run_id, seq, "recommendation", recommendation)
                        seq += 1

                    episode_id = update.get("episode_id")
                    if episode_id:
                        run["episode_id"] = episode_id

                    critic = update.get("critic")
                    if critic and critic.get("requires_hitl"):
                        yield _envelope(
                            run_id,
                            seq,
                            "hitl.required",
                            {
                                "reason": "High risk or low confidence action requires approval.",
                                "recommendation_id": (run.get("recommendation") or {}).get("id"),
                                "confidence": critic.get("confidence_reviewed"),
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
                    "episode_id": run.get("episode_id"),
                },
            )
            seq += 1
        except Exception:  # noqa: BLE001 - log detail server-side, keep client generic
            logger.exception("run %s failed during streaming", run_id)
            run["status"] = "error"
            yield _envelope(
                run_id, seq, "error", {"message": "internal error during run"}
            )

    return EventSourceResponse(event_generator())


async def _record_and_distill(
    run: Dict[str, Any], decision: str, reason: Optional[str], outcome: Optional[Dict[str, Any]]
) -> None:
    """Write the human decision to memory and trigger distillation.

    Best-effort: if the memory slice is unavailable this is a no-op so the API
    still returns success.
    """

    try:
        from app.agents import safe_get_memory
    except Exception:  # noqa: BLE001
        return

    memory = await safe_get_memory()
    if memory is None:
        return

    episode_id = run.get("episode_id")
    if episode_id:
        try:
            await memory.record_outcome(
                episode_id=episode_id,
                decision=decision,
                reason=reason,
                outcome=outcome,
            )
        except Exception:  # noqa: BLE001
            pass

    # Trigger distillation if the memory slice exposes it (name may vary).
    for attr in ("distill", "run_distillation", "consolidate"):
        fn = getattr(memory, attr, None)
        if callable(fn):
            try:
                result = fn(run.get("domain"))
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001
                pass
            break


@router.post("/runs/{run_id}/hitl")
async def hitl(
    run_id: str, body: HitlIn, org_id: str = Depends(current_org)
) -> Dict[str, str]:
    """Record a human in the loop decision and close the learning loop."""

    run = _get_owned_run(run_id, org_id)
    if body.decision not in {"approve", "reject", "edit"}:
        raise HTTPException(status_code=422, detail="invalid decision")

    edited = (
        body.edited_action.model_dump(exclude_none=True) if body.edited_action else None
    )
    run["hitl"] = {
        "decision": body.decision,
        "edited_action": edited,
        "reason": body.reason,
        "recorded_at": _now_iso(),
    }

    recommendation = run.get("recommendation")
    outcome: Optional[Dict[str, Any]] = None
    if recommendation:
        status_map = {"approve": "approved", "reject": "rejected", "edit": "edited"}
        recommendation["status"] = status_map[body.decision]
        if body.decision == "edit" and edited:
            recommendation["action"] = {**recommendation["action"], **edited}
        outcome = {
            "action_key": (recommendation.get("action") or {}).get("key"),
            "status": recommendation["status"],
            "confidence": (recommendation.get("confidence") or {}).get("score"),
            "expected_impact": recommendation.get("expected_impact"),
        }

    await _record_and_distill(run, body.decision, body.reason, outcome)

    return {"status": "recorded"}
