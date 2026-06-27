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
from typing import Any, AsyncIterator, Dict, List, Optional

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


@router.get("/runs")
async def list_runs(org_id: str = Depends(current_org)) -> Dict[str, Any]:
    """List the caller's recent runs, newest first, for the run history UI."""

    # One-shot id -> name map so each run shows the account name, not the id.
    name_by_id: Dict[str, str] = {}
    try:
        from app.api.accounts import _org_accounts

        for acct in await _org_accounts(org_id, None):
            aid = acct.get("account_id")
            if aid:
                name_by_id[aid] = acct.get("name") or aid
    except Exception:  # noqa: BLE001 - names are best effort
        pass

    # In-memory runs (this process) plus DURABLE episode-derived runs, so the
    # history survives a restart (the _RUNS registry does not).
    runs: List[Dict[str, Any]] = [
        r for r in _RUNS.values() if r.get("org_id") == org_id
    ]
    seen_ep = {r.get("episode_id") for r in runs if r.get("episode_id")}
    try:
        from app.api._org import DEMO_ORG
        from app.memory.store import get_memory

        for ep in get_memory().all_episodes():
            ep_org = getattr(ep, "org_id", None) or DEMO_ORG
            if ep_org != org_id:
                continue
            eid = getattr(ep, "id", None)
            if eid in seen_ep:
                continue
            runs.append(
                {
                    "run_id": eid,
                    "org_id": ep_org,
                    "account_id": getattr(ep, "account_id", None),
                    "domain": getattr(ep, "domain", None),
                    "status": "finished",
                    "recommendation": getattr(ep, "recommendation", None),
                    "signal": {"content": getattr(ep, "situation", "") or ""},
                    "created_at": getattr(ep, "created_at", None),
                    "episode_id": eid,
                }
            )
    except Exception:  # noqa: BLE001 - durable runs are best effort
        pass

    items: List[Dict[str, Any]] = []
    for run in runs:
        rec = run.get("recommendation") or {}
        action = rec.get("action")
        action_title = (
            action.get("title")
            if isinstance(action, dict)
            else (action or rec.get("action_title"))
        )
        conf = rec.get("confidence")
        score = conf.get("score") if isinstance(conf, dict) else conf
        sig = run.get("signal") or {}
        items.append(
            {
                "run_id": run.get("run_id"),
                "account_id": run.get("account_id"),
                "account_name": name_by_id.get(run.get("account_id"))
                or run.get("account_id"),
                "domain": run.get("domain"),
                "status": run.get("status"),
                "created_at": run.get("created_at"),
                "signal_summary": (sig.get("summary") or sig.get("text") or "")[:140]
                or None,
                "action_title": action_title,
                "confidence": score,
                "has_recommendation": bool(rec),
            }
        )
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return {"runs": items[:50]}


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    org_id: str = Depends(current_org),
    disable_memory: bool = False,
) -> EventSourceResponse:
    """Stream the graph execution as Server Sent Events.

    ``disable_memory`` (query param) threads ``state['disable_memory'] = True``
    into the graph so an A/B toggle can re-run the same signal without the
    learned-memory re-ranking, making the learning loop's lift visible side by
    side. It does not change the event contract.
    """

    run = _get_owned_run(run_id, org_id)

    # Bind the caller's org so the synchronous graph (whose nodes call
    # ``load_pack(domain)`` with no org argument) resolves THIS org's uploaded
    # domain pack, never another tenant's. Hydration repopulates the loader
    # registry from durable storage for a fresh process. Done outside the
    # generator so a binding failure cannot break the SSE stream.
    from app.packs.loader import reset_pack_org, set_pack_org
    from app.repositories import org_packs as org_packs_repo

    try:
        await org_packs_repo.hydrate_loader(org_id)
    except Exception:  # noqa: BLE001 - hydration is best effort
        logger.warning("org pack hydration failed for org %s", org_id)

    async def event_generator() -> AsyncIterator[Dict[str, str]]:
        seq = 0
        run["status"] = "running"
        pack_token = set_pack_org(org_id)

        yield _envelope(
            run_id,
            seq,
            "run.started",
            {"domain": run["domain"], "account_id": run["account_id"]},
        )
        seq += 1

        # Resolve the account's display name (org-scoped) so recommendations and
        # drafts refer to it by name, never the internal id.
        account_name = run.get("account_id")
        account_ctx: Dict[str, Any] = {}
        try:
            from app.api.accounts import _org_account

            if run.get("account_id"):
                acct = await _org_account(org_id, run["account_id"])
                if acct:
                    account_ctx = acct
                    account_name = acct.get("name") or account_name
        except Exception:  # noqa: BLE001 - name is best effort
            pass

        initial_state = {
            "run_id": run_id,
            "org_id": run.get("org_id"),
            "domain": run["domain"],
            "account_id": run["account_id"],
            "account_name": account_name,
            "account": account_ctx,
            "signal": run["signal"],
            "plan": [],
            "capabilities": [],
            "steps": [],
            "messages": [],
            "recommendation": None,
            # A/B toggle: when set, the graph skips learned-memory re-ranking so
            # the same signal can be compared with and without the learning loop.
            "disable_memory": disable_memory,
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
        finally:
            reset_pack_org(pack_token)

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


async def _episode_outcome(episode_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the recorded outcome for an episode, or None.

    Reads the human decision and any measured metrics from the memory slice so
    the brief can show how the recommendation actually played out. Offline-safe:
    if the memory slice is unavailable this is a no-op. The episode is already
    bound to an org-scoped run, so no extra authz check is needed here.
    """

    if not episode_id:
        return None
    try:
        from app.agents import safe_get_memory
    except Exception:  # noqa: BLE001
        return None

    memory = await safe_get_memory()
    if memory is None:
        return None
    try:
        episodes = memory.all_episodes()
    except Exception:  # noqa: BLE001
        return None

    for ep in episodes:
        if getattr(ep, "id", None) != episode_id:
            continue
        outcome = getattr(ep, "outcome", None)
        if outcome is None:
            return None
        decision = getattr(outcome, "decision", "pending")
        if decision in (None, "", "pending"):
            return None
        return {
            "decision": decision,
            "reason": getattr(outcome, "reason", None),
            "metrics": dict(getattr(outcome, "metrics", {}) or {}),
            "recorded_at": getattr(outcome, "recorded_at", None),
        }
    return None


async def _build_brief(run: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble a self-contained decision brief from stored run + episode state.

    No re-run and no LLM: every field is read from the persisted run, its
    recommendation, the HITL record, and the episode outcome. Account context is
    enriched best-effort from the accounts slice. Offline-safe throughout.
    """

    rec: Dict[str, Any] = dict(run.get("recommendation") or {})
    account_id = run.get("account_id", "")
    domain = run.get("domain", "")

    # Best-effort account enrichment (name, health). Falls back to the id.
    account: Dict[str, Any] = {
        "account_id": account_id,
        "name": account_id,
        "domain": domain,
        "health_score": None,
        "stage": None,
    }
    try:
        from app.api.accounts import _org_account

        record = await _org_account(run.get("org_id", ""), account_id)
        if record:
            account.update(
                {
                    "name": record.get("name", account_id),
                    "health_score": record.get("health_score"),
                    "stage": record.get("stage") or record.get("lifecycle_stage"),
                }
            )
    except Exception:  # noqa: BLE001 - enrichment is optional
        pass

    confidence = rec.get("confidence") or {}
    policy_results = rec.get("policy")
    policy_block: Optional[Dict[str, Any]] = None
    if policy_results is not None:
        passed = sum(1 for g in policy_results if g.get("status") == "pass")
        warned = sum(1 for g in policy_results if g.get("status") == "warn")
        failed = sum(1 for g in policy_results if g.get("status") == "fail")
        policy_block = {
            "results": policy_results,
            "summary": {
                "total": len(policy_results),
                "passed": passed,
                "warned": warned,
                "failed": failed,
                "requires_approval": any(
                    g.get("requires_approval") and g.get("status") != "pass"
                    for g in policy_results
                ),
            },
        }

    hitl = run.get("hitl")
    human_decision: Optional[Dict[str, Any]] = None
    if hitl:
        human_decision = {
            "decision": hitl.get("decision"),
            "edited_action": hitl.get("edited_action"),
            "reason": hitl.get("reason"),
            "recorded_at": hitl.get("recorded_at"),
        }

    outcome = await _episode_outcome(run.get("episode_id"))

    return {
        "run_id": run.get("run_id"),
        "generated_at": _now_iso(),
        "status": run.get("status"),
        "account": account,
        "signal": run.get("signal") or {},
        "recommendation": {
            "id": rec.get("id"),
            "status": rec.get("status"),
            "action": rec.get("action") or {},
            "reasoning": rec.get("rationale", ""),
            "risk_opportunity": rec.get("risk_opportunity"),
            "counterfactual": rec.get("counterfactual"),
        },
        "confidence": {
            "score": confidence.get("score"),
            "label": confidence.get("label"),
            "method": confidence.get("method"),
        },
        "expected_impact": rec.get("expected_impact"),
        "evidence": rec.get("evidence") or [],
        "signals": rec.get("signals") or {"supporting": [], "contradicting": []},
        "alternatives": rec.get("alternatives") or [],
        "policy": policy_block,
        "missing_information": rec.get("missing_information") or [],
        "human_decision": human_decision,
        "outcome": outcome,
    }


@router.get("/runs/{run_id}/brief")
async def run_brief(
    run_id: str, org_id: str = Depends(current_org)
) -> Dict[str, Any]:
    """Return a self-contained, exportable decision brief for a run.

    Read-only and org-scoped: it never re-runs the graph or calls an LLM, it
    only projects the stored run, recommendation, policy gate, human decision,
    and episode outcome into a one-page artifact. Returns 404 for unknown or
    other-org runs (same ownership rule as the rest of the runs API), and 409
    while a run has not yet produced a recommendation.
    """

    run = _get_owned_run(run_id, org_id)
    if not run.get("recommendation"):
        raise HTTPException(status_code=409, detail="run has no recommendation yet")
    return await _build_brief(run)


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
