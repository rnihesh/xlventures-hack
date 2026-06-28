"""OpenAI usage accounting, attributed per org.

Token usage is captured at two choke points (chat/agent completions via a
LangChain callback on ``get_llm``, and embeddings in the retrieval layer) into a
request-scoped in-memory sink, then flushed to the ``usage_events`` table once
per request by the ``record_usage`` context manager. Nothing here ever raises
into the request path: accounting is best effort.

Why a sink plus a single flush (instead of writing in the callback): the
callback may run in any async task, and we want exactly one durable write per
request with the org attached, not a DB round trip per LLM call.
"""

from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field

logger = logging.getLogger("app.usage")


@dataclass
class _Entry:
    kind: str  # "completion" | "embedding"
    model: str
    input_tokens: int
    output_tokens: int


@dataclass
class UsageSink:
    entries: list[_Entry] = field(default_factory=list)


_sink: ContextVar[UsageSink | None] = ContextVar("usage_sink", default=None)


def record_completion(model: str | None, input_tokens: int, output_tokens: int) -> None:
    sink = _sink.get()
    if sink is None:
        return
    sink.entries.append(
        _Entry("completion", model or "unknown", int(input_tokens or 0), int(output_tokens or 0))
    )


def record_embedding(model: str | None, total_tokens: int) -> None:
    sink = _sink.get()
    if sink is None:
        return
    sink.entries.append(_Entry("embedding", model or "unknown", int(total_tokens or 0), 0))


try:
    from langchain_core.callbacks.base import BaseCallbackHandler as _BaseCB
except Exception:  # noqa: BLE001 - keep usage import-safe even if langchain shifts
    _BaseCB = object  # type: ignore[assignment, misc]


class UsageCallback(_BaseCB):  # type: ignore[valid-type, misc]
    """Records completion token usage to the sink.

    SYNCHRONOUS on purpose: the graph specialists call ``llm.invoke`` (sync), so
    an async-only handler would error those calls and silently force the whole
    planner into its deterministic fallback. A sync BaseCallbackHandler runs on
    both ``invoke`` and ``ainvoke`` and never breaks a model call.
    """

    raise_error = False

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001
        try:
            model, in_tok, out_tok = _extract_usage(response)
            if in_tok or out_tok:
                record_completion(model, in_tok, out_tok)
        except Exception as exc:  # noqa: BLE001 - accounting never breaks a run
            logger.debug("usage capture failed: %s", exc)


def _extract_usage(response) -> tuple[str | None, int, int]:  # noqa: ANN001
    """Pull (model, input_tokens, output_tokens) from a LangChain LLMResult."""
    model = None
    in_tok = out_tok = 0
    llm_output = getattr(response, "llm_output", None) or {}
    if isinstance(llm_output, dict):
        model = llm_output.get("model_name") or llm_output.get("model")
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        in_tok = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
        out_tok = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
    if not (in_tok or out_tok):
        # Newer langchain: usage on the message of the first generation.
        try:
            gen = response.generations[0][0]
            meta = getattr(getattr(gen, "message", None), "usage_metadata", None) or {}
            in_tok = meta.get("input_tokens", 0)
            out_tok = meta.get("output_tokens", 0)
            model = model or getattr(gen.message, "response_metadata", {}).get("model_name")
        except Exception:  # noqa: BLE001
            pass
    return model, int(in_tok or 0), int(out_tok or 0)


def open_sink():
    """Start a usage sink in the current context. Returns the reset token."""
    return _sink.set(UsageSink())


async def flush_sink(token, org_id: str | None) -> None:  # noqa: ANN001
    """Flush and close the sink opened with :func:`open_sink`."""
    sink = _sink.get()
    try:
        _sink.reset(token)
    except Exception:  # noqa: BLE001 - token from a different context
        pass
    if org_id and sink and sink.entries:
        try:
            await _flush(org_id, sink)
        except Exception as exc:  # noqa: BLE001
            logger.warning("usage flush failed: %s", exc)


@contextlib.asynccontextmanager
async def record_usage(org_id: str | None):
    """Open a usage sink for the duration of a request, flush on exit."""
    token = open_sink()
    try:
        yield
    finally:
        await flush_sink(token, org_id)


async def _flush(org_id: str, sink: UsageSink) -> None:
    from app.repositories import usage as usage_repo
    from app.services.pricing import cost_usd

    # Aggregate by (kind, model) so a multi-call run writes a handful of rows.
    agg: dict[tuple[str, str], list[int]] = {}
    for e in sink.entries:
        key = (e.kind, e.model)
        acc = agg.setdefault(key, [0, 0])
        acc[0] += e.input_tokens
        acc[1] += e.output_tokens
    rows = []
    for (kind, model), (in_tok, out_tok) in agg.items():
        rows.append(
            {
                "org_id": org_id,
                "kind": kind,
                "model": model,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
                "cost_usd": round(cost_usd(model, in_tok, out_tok), 6),
            }
        )
    await usage_repo.insert_events(rows)
