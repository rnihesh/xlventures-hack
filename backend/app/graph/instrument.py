"""Tool-call instrumentation for planner / specialist nodes.

A tiny, dependency-free helper that wraps a graph node so its execution is
recorded as a typed tool invocation in ``state['steps']``. Every instrumented
step carries one consistent shape::

    {
        "node": str,             # graph node name
        "tool": str,             # logical tool / capability invoked
        "summary": str,          # short human summary (kept for run-trace)
        "ts": str,               # ISO finish time (kept for run-trace)
        "inputs_summary": str,   # what the tool was called with
        "outputs_summary": str,  # what the tool produced
        "started": str,          # ISO start time
        "finished": str,         # ISO finish time
        "latency_ms": float,     # wall-clock duration in milliseconds
        "data": {                # same fields, nested for the SSE envelope
            "tool": str,
            "inputs_summary": str,
            "outputs_summary": str,
            "started": str,
            "finished": str,
            "latency_ms": float,
            ...extra,
        },
    }

The instrumentation fields are mirrored inside ``data`` on purpose: the runs API
forwards ``steps[-1]['summary']`` and ``steps[-1]['data']`` verbatim onto the
``node.finished`` event, so nesting the fields lets the live tool-call view read
them without any change to the frozen event schema.

This module has no heavy dependencies (stdlib only) so it can be imported from
the planner, the specialist nodes, or a test harness without side effects.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Optional

__all__ = [
    "make_tool_step",
    "instrument_node",
    "wrap_node",
    "summarize_state_inputs",
    "summarize_update_outputs",
]

# A node returns a partial state update (a dict) that LangGraph merges back in.
NodeFn = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
Summarizer = Callable[[Dict[str, Any]], str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _truncate(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _summarize_value(value: Any) -> str:
    """Render one state value as a short, type-aware fragment."""

    if value is None:
        return "∅"
    if isinstance(value, str):
        return _truncate(value, 80) if value else "''"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        keys = list(value.keys())
        shown = ", ".join(str(k) for k in keys[:4])
        more = "…" if len(keys) > 4 else ""
        return f"{{{shown}{more}}}" if keys else "{}"
    if isinstance(value, (list, tuple, set)):
        return f"[{len(value)} item{'s' if len(value) != 1 else ''}]"
    return _truncate(repr(value), 60)


# Keys that make for a readable "inputs" line, in priority order.
_INPUT_KEYS = ("signal", "account_id", "domain", "decision_point", "capabilities")
# Channels that are bookkeeping rather than tool output.
_OUTPUT_SKIP = {"steps", "messages"}


def summarize_state_inputs(state: Dict[str, Any]) -> str:
    """Default inputs summary: the salient fields a node reads from state."""

    parts = []
    signal = state.get("signal") or {}
    if isinstance(signal, dict) and signal.get("content"):
        parts.append(f"signal: {_truncate(str(signal.get('content')), 90)}")
    for key in _INPUT_KEYS:
        if key == "signal":
            continue
        value = state.get(key)
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}: {_summarize_value(value)}")
    return "; ".join(parts) if parts else "(initial state)"


def summarize_update_outputs(update: Dict[str, Any]) -> str:
    """Default outputs summary: the state delta a node produced."""

    if not update:
        return "(no state delta)"
    parts = [
        f"{key}: {_summarize_value(value)}"
        for key, value in update.items()
        if key not in _OUTPUT_SKIP
    ]
    if not parts:
        # Node only appended trace/messages; surface its own summary instead.
        steps = update.get("steps") or []
        if steps and isinstance(steps[-1], dict):
            summary = steps[-1].get("summary")
            if summary:
                return _truncate(str(summary), 120)
        return "(trace only)"
    return "; ".join(parts)


def make_tool_step(
    node: str,
    tool: str,
    inputs_summary: str,
    outputs_summary: str,
    started: datetime,
    finished: datetime,
    *,
    summary: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a single instrumented trace step in the canonical shape."""

    latency_ms = round(max(0.0, (finished - started).total_seconds()) * 1000.0, 2)
    instrumentation: Dict[str, Any] = {
        "tool": tool,
        "inputs_summary": inputs_summary,
        "outputs_summary": outputs_summary,
        "started": _iso(started),
        "finished": _iso(finished),
        "latency_ms": latency_ms,
    }
    data: Dict[str, Any] = dict(instrumentation)
    if extra:
        data.update(extra)
    return {
        "node": node,
        "ts": _iso(finished),
        "summary": summary or outputs_summary,
        "data": data,
        **instrumentation,
    }


def _enrich_existing_step(
    step: Dict[str, Any],
    node: str,
    tool: str,
    inputs_summary: str,
    outputs_summary: str,
    started: datetime,
    finished: datetime,
) -> Dict[str, Any]:
    """Fold instrumentation into a step the node already produced.

    The node's own ``summary`` and bespoke ``data`` are preserved (so the
    existing planner trace keeps reading), and the tool-call fields are added at
    the top level and mirrored inside ``data`` for the event envelope.
    """

    latency_ms = round(max(0.0, (finished - started).total_seconds()) * 1000.0, 2)
    instrumentation = {
        "tool": tool,
        "inputs_summary": inputs_summary,
        "outputs_summary": outputs_summary,
        "started": _iso(started),
        "finished": _iso(finished),
        "latency_ms": latency_ms,
    }
    merged = dict(step)
    merged.setdefault("node", node)
    merged.setdefault("ts", _iso(finished))
    data = dict(merged.get("data") or {})
    # Node-provided data wins on key collisions; instrumentation only fills gaps.
    for key, value in instrumentation.items():
        data.setdefault(key, value)
    merged["data"] = data
    for key, value in instrumentation.items():
        merged.setdefault(key, value)
    return merged


def wrap_node(
    fn: NodeFn,
    *,
    tool: Optional[str] = None,
    node: Optional[str] = None,
    summarize_inputs: Summarizer = summarize_state_inputs,
    summarize_outputs: Summarizer = summarize_update_outputs,
) -> NodeFn:
    """Wrap an async node so its run is recorded as a typed tool invocation.

    The wrapper times the call, summarizes the inputs (read from ``state``) and
    the outputs (the returned update), then either enriches the step the node
    already appended or appends a fresh instrumented step. The accumulating
    ``steps`` reducer means returning exactly one step per node keeps the trace
    one-to-one with executions.
    """

    node_name = node or (getattr(fn, "__name__", "node") or "node").removesuffix("_node")
    tool_name = tool or node_name

    @wraps(fn)
    async def _wrapped(state: Dict[str, Any]) -> Dict[str, Any]:
        started = _now()
        started_perf = time.perf_counter()
        inputs_summary = _safe_summary(summarize_inputs, state, "(inputs unavailable)")

        result = fn(state)
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[assignment]
        update: Dict[str, Any] = dict(result or {})

        finished = started + _delta_since(started_perf)
        outputs_summary = _safe_summary(
            summarize_outputs, update, "(outputs unavailable)"
        )

        steps = list(update.get("steps") or [])
        if steps and isinstance(steps[-1], dict):
            steps[-1] = _enrich_existing_step(
                steps[-1],
                node_name,
                tool_name,
                inputs_summary,
                outputs_summary,
                started,
                finished,
            )
        else:
            steps.append(
                make_tool_step(
                    node_name,
                    tool_name,
                    inputs_summary,
                    outputs_summary,
                    started,
                    finished,
                )
            )
        update["steps"] = steps
        return update

    return _wrapped


def instrument_node(
    tool: Optional[str] = None,
    *,
    node: Optional[str] = None,
    summarize_inputs: Summarizer = summarize_state_inputs,
    summarize_outputs: Summarizer = summarize_update_outputs,
) -> Callable[[NodeFn], NodeFn]:
    """Decorator form of :func:`wrap_node`.

    Usage::

        @instrument_node(tool="risk_scorer")
        async def node(state): ...
    """

    def _decorator(fn: NodeFn) -> NodeFn:
        return wrap_node(
            fn,
            tool=tool,
            node=node,
            summarize_inputs=summarize_inputs,
            summarize_outputs=summarize_outputs,
        )

    return _decorator


def _delta_since(started_perf: float):
    from datetime import timedelta

    return timedelta(seconds=max(0.0, time.perf_counter() - started_perf))


def _safe_summary(summarizer: Summarizer, payload: Dict[str, Any], fallback: str) -> str:
    try:
        text = summarizer(payload)
        return text if isinstance(text, str) and text else fallback
    except Exception:  # noqa: BLE001 - instrumentation must never break a run
        return fallback
