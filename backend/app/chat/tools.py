"""Tool registry for the agentic chatbot.

Every capability the platform exposes through its REST API is also exposed here
as a thin, callable TOOL so a conversational agent can use the whole product:
triage accounts, inspect domain packs, run an NBA decision, search the knowledge
base with citations, evaluate policy, generate an artifact, ingest an
interaction, and read the learning and eval surfaces.

These wrappers do NOT duplicate business logic. Each one calls the existing
service (the route handler or its underlying function) and normalizes the result
into a JSON-serializable dict. The registry is the single tool layer shared by
both agent paths: real LLM tool-calling when an OpenAI key is present, and the
deterministic offline router when it is not.
"""

from __future__ import annotations

import contextvars
import functools
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Org scoping
# ---------------------------------------------------------------------------
# The chat endpoints run inside a single request/task, so a context variable is
# a safe place to stash the caller's org for the duration of a turn. The agent
# sets it from the request context before any tool runs; tools that touch
# org-scoped state (runs, connectors) read it here. Offline (no auth) this
# resolves to the demo org so the deterministic path is fully deterministic.
_ORG_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "chat_org_id", default=None
)


def set_current_org(org_id: Optional[str]) -> None:
    """Bind the org for the current chat turn (called by the agent)."""

    _ORG_VAR.set(org_id or None)


def current_org_id() -> str:
    """Resolve the active org, defaulting to the demo org offline."""

    val = _ORG_VAR.get()
    if val:
        return val
    try:
        from app.api._org import DEMO_ORG

        return DEMO_ORG
    except Exception:  # noqa: BLE001 - org slice optional
        return "org_demo"


# ---------------------------------------------------------------------------
# Tool model
# ---------------------------------------------------------------------------
@dataclass
class Tool:
    """A single callable capability exposed to the agent.

    ``parameters`` is a JSON Schema object describing the tool's arguments (the
    same shape OpenAI tool-calling expects). ``run`` is an async callable that
    accepts the arguments as keyword args and returns a JSON-serializable value.
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    run: Callable[..., Awaitable[Any]]

    def to_openai(self) -> Dict[str, Any]:
        """Render this tool in the OpenAI ``tools`` schema for bind_tools."""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Tool implementations (thin wrappers over existing services)
# ---------------------------------------------------------------------------
async def list_accounts(domain: Optional[str] = None) -> Dict[str, Any]:
    """Return the triage inbox (highest risk first), optionally scoped by domain."""

    from app.api.accounts import list_accounts as _list_accounts

    accounts = await _list_accounts(domain=domain)
    return {"count": len(accounts), "accounts": accounts}


async def get_account(account_id: str) -> Dict[str, Any]:
    """Return the account 360 (profile, signals, history, documents)."""

    from fastapi import HTTPException

    from app.api.accounts import get_account as _get_account

    try:
        return await _get_account(account_id)
    except HTTPException as exc:
        return {"error": exc.detail, "account_id": account_id}


async def list_domains() -> Dict[str, Any]:
    """Return every domain pack on disk (the reusable verticals)."""

    from app.api.domains import get_domains as _get_domains

    packs = await _get_domains()
    return {"count": len(packs), "domains": packs}


async def get_domain(domain_key: str) -> Dict[str, Any]:
    """Return the full parsed pack for one domain."""

    from fastapi import HTTPException

    from app.api.domains import get_domain as _get_domain

    try:
        return await _get_domain(domain_key)
    except HTTPException as exc:
        return {"error": exc.detail, "domain_key": domain_key}


async def run_nba(
    account_id: str,
    signal_text: str,
    domain: str = "customer_success",
) -> Dict[str, Any]:
    """Run the full LangGraph NBA pipeline and return the recommendation.

    Drives the same planner graph the runs API streams, but synchronously to a
    final state. The run is registered in the runs registry so a follow-up
    ``execute_action`` can reference it by ``run_id``.
    """

    from app.api.runs import _RUNS
    from app.deps import get_checkpointer
    from app.graph.planner import build_graph

    run_id = str(uuid.uuid4())
    org_id = current_org_id()
    signal = {"type": "", "content": signal_text}
    initial_state: Dict[str, Any] = {
        "run_id": run_id,
        "org_id": org_id,
        "domain": domain,
        "account_id": account_id,
        "signal": signal,
        "plan": [],
        "capabilities": [],
        "steps": [],
        "messages": [],
        "recommendation": None,
    }
    config = {"configurable": {"thread_id": run_id}}

    checkpointer = await get_checkpointer()
    graph = build_graph(checkpointer)
    final = await graph.ainvoke(initial_state, config=config)

    recommendation = final.get("recommendation")
    episode_id = final.get("episode_id")

    # Register the run so artifact execution can resolve it by id later.
    _RUNS[run_id] = {
        "run_id": run_id,
        "org_id": org_id,
        "domain": domain,
        "account_id": account_id,
        "signal": signal,
        "status": "finished",
        "recommendation": recommendation,
        "episode_id": episode_id,
        "hitl": None,
        "created_at": _now_iso(),
    }

    critic = final.get("critic") or {}
    return {
        "run_id": run_id,
        "domain": domain,
        "account_id": account_id,
        "decision_point": final.get("decision_point"),
        "recommendation": recommendation,
        "requires_hitl": bool(critic.get("requires_hitl")),
        "episode_id": episode_id,
        "steps": [
            {"node": s.get("agent") or s.get("node"), "summary": s.get("summary")}
            for s in (final.get("steps") or [])
        ],
    }


async def search_knowledge(
    query: str,
    account_id: Optional[str] = None,
    domain: str = "customer_success",
    k: int = 5,
) -> Dict[str, Any]:
    """Search the knowledge corpus and return chunks plus span-exact citations."""

    from app.retrieval.store import get_retriever

    retriever = get_retriever(domain)
    evidence = await retriever.search(query, account_id=account_id, k=k)

    chunks: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    for ev in evidence:
        data = ev.model_dump()
        chunks.append(data)
        citations.append(
            {
                "source_id": data["source_id"],
                "source_type": data["source_type"],
                "snippet": data["snippet"],
                "span": data["span"],
                "score": data["score"],
            }
        )
    return {"query": query, "count": len(chunks), "chunks": chunks, "citations": citations}


async def evaluate_policy(
    recommendation: Dict[str, Any],
    domain: str = "customer_success",
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate a recommendation against a domain's declarative policy gates."""

    from app.api.policy import EvaluateRequest
    from app.api.policy import evaluate_policy as _evaluate_policy

    req = EvaluateRequest(
        recommendation=recommendation or {},
        account_id=account_id,
        domain=domain,
    )
    return await _evaluate_policy(req)


async def execute_action(
    artifact_type: str,
    run_id: Optional[str] = None,
    recommendation: Optional[Dict[str, Any]] = None,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a concrete artifact (email | crm_task | slack) from a rec or run."""

    from fastapi import HTTPException

    from app.api.execute import ExecuteIn
    from app.api.execute import execute as _execute

    body = ExecuteIn(
        run_id=run_id,
        recommendation=recommendation,
        account_id=account_id,
        artifact_type=artifact_type,
    )
    try:
        out = await _execute(body)
    except HTTPException as exc:
        return {"error": exc.detail, "artifact_type": artifact_type}
    return out.model_dump()


# ---------------------------------------------------------------------------
# Run references and sending (chat acts on a prior run for the caller's org)
# ---------------------------------------------------------------------------
# A channel name (what the user says) maps to a connector kind (what the
# connectors repository stores).
_CHANNEL_KIND = {
    "email": "ses",
    "ses": "ses",
    "slack": "slack",
    "google": "google",
    "gmail": "google",
}


def _all_runs() -> Dict[str, Dict[str, Any]]:
    """Return the in-memory run registry (shared with the runs API)."""

    try:
        from app.api.runs import _RUNS

        return _RUNS
    except Exception:  # noqa: BLE001 - runs slice optional
        return {}


def _find_run(run_id: str, org_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a run the caller's org owns (never leak another org's run)."""

    run = _all_runs().get(run_id)
    if run is None:
        return None
    owner = run.get("org_id")
    if owner is not None and owner != org_id:
        return None
    return run


def _org_runs(org_id: str) -> List[Dict[str, Any]]:
    """Return the org's runs, most recent first."""

    runs = [r for r in _all_runs().values() if r.get("org_id") == org_id]
    return sorted(runs, key=lambda r: r.get("created_at") or "", reverse=True)


def _run_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a stored run into the chat-facing shape."""

    rec = run.get("recommendation")
    action = (rec or {}).get("action") or {}
    return {
        "run_id": run.get("run_id"),
        "org_id": run.get("org_id"),
        "account_id": run.get("account_id"),
        "domain": run.get("domain"),
        "status": run.get("status"),
        "created_at": run.get("created_at"),
        "action_title": action.get("title"),
        "recommendation": rec,
        "tags": run.get("tags", []),
    }


async def get_run(run_id: str) -> Dict[str, Any]:
    """Return one of the org's runs (with its stored recommendation) by id."""

    org_id = current_org_id()
    run = _find_run(run_id, org_id)
    if run is None:
        return {"found": False, "error": f"run not found: {run_id}", "run_id": run_id}
    out = _run_summary(run)
    out["found"] = True
    return out


async def get_last_run(account_id: Optional[str] = None) -> Dict[str, Any]:
    """Return the org's most recent run, optionally for a single account.

    Prefers the most recent run that actually produced a recommendation so a
    follow-up ``send_artifact`` has something to deliver.
    """

    org_id = current_org_id()
    runs = _org_runs(org_id)
    if account_id:
        aid = account_id.upper()
        runs = [r for r in runs if (r.get("account_id") or "").upper() == aid]
    if not runs:
        return {
            "found": False,
            "message": "No runs yet for this org. Run an NBA decision first, then I can act on it.",
        }
    chosen = next((r for r in runs if r.get("recommendation")), runs[0])
    out = _run_summary(chosen)
    out["found"] = True
    return out


async def tag_run(
    run_id: Optional[str] = None,
    account_id: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Associate a run with an account and/or a free-text note.

    Defaults to the org's most recent run when no ``run_id`` is given so the
    user can say 'tag this run with Northwind' right after a decision.
    """

    org_id = current_org_id()
    if run_id:
        run = _find_run(run_id, org_id)
    else:
        runs = _org_runs(org_id)
        run = runs[0] if runs else None
    if run is None:
        return {"error": "no run to tag; run an NBA decision first", "run_id": run_id}

    tag = {
        "account_id": account_id.upper() if account_id else None,
        "note": note,
        "tagged_at": _now_iso(),
    }
    run.setdefault("tags", []).append(tag)
    return {"run_id": run.get("run_id"), "tagged": tag, "tags": run["tags"]}


def _connector_ready(kind: str, connector: Optional[Dict[str, Any]]) -> bool:
    """True when a connector record carries the config needed to send."""

    config = (connector or {}).get("config") or {}
    if kind == "ses":
        return bool(config.get("sender_email"))
    if kind == "slack":
        return bool(config.get("webhook_url"))
    if kind == "google":
        return bool(config.get("access_token") or config.get("refresh_token"))
    return False


def _connect_hint(channel: str) -> str:
    """A friendly nudge to connect a channel that is not configured yet."""

    names = {
        "email": "Amazon SES email",
        "ses": "Amazon SES email",
        "slack": "Slack",
        "gmail": "Gmail",
        "google": "Gmail",
    }
    label = names.get(channel, channel)
    return (
        f"{label} is not connected for your org. Connect it in "
        "Settings > Integrations, then ask me again."
    )


def _lookup_account_record(account_id: Optional[str]) -> Dict[str, Any]:
    """Resolve account context (best-effort, tolerant of missing slices)."""

    if not account_id:
        return {}
    try:
        from app.api.execute import _lookup_account

        return _lookup_account(account_id) or {}
    except Exception:  # noqa: BLE001 - accounts slice optional
        return {}


def _recipient(account_id: Optional[str]) -> Optional[str]:
    """Pick the best email recipient for an account."""

    account = _lookup_account_record(account_id)
    return (
        account.get("email")
        or account.get("contact_email")
        or account.get("owner_email")
    )


def _send_slack(webhook_url: Optional[str], text: str) -> Dict[str, Any]:
    try:
        from app.services.slack import post_message
    except Exception as exc:  # noqa: BLE001 - service optional / offline
        return {"sent": False, "reason": "slack_unavailable", "detail": str(exc)}
    return post_message(webhook_url, text)


def _send_email(
    to: Optional[str], subject: str, body: str, sender: Optional[str]
) -> Dict[str, Any]:
    if not to:
        return {"sent": False, "reason": "no_recipient"}
    try:
        from app.services.email import send_email
    except Exception:  # noqa: BLE001 - send_email may be unavailable offline
        return {"sent": False, "reason": "ses_not_configured"}
    return send_email(to, subject, body, sender)


def _send_gmail(
    connector: Dict[str, Any], to: Optional[str], subject: str, body: str
) -> Dict[str, Any]:
    if not to:
        return {"sent": False, "reason": "no_recipient"}
    try:
        from app.services.google_oauth import send_gmail
    except Exception as exc:  # noqa: BLE001 - service optional / offline
        return {"sent": False, "reason": "google_not_connected", "detail": str(exc)}
    return send_gmail(connector, to, subject, body)


async def send_artifact(
    channel: str = "email",
    run_id: Optional[str] = None,
    recommendation: Optional[Dict[str, Any]] = None,
    account_id: Optional[str] = None,
    to: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a run's recommendation to a channel using the org's connectors.

    Resolves the recommendation (inline, by ``run_id``, or the org's most
    recent run), generates the matching artifact (email or Slack message), and
    delivers it through the org's configured connector. Refuses (never raises)
    when the channel is not connected, telling the user to connect it in
    Settings. This is the same send path the execute API uses.
    """

    org_id = current_org_id()
    channel = (channel or "email").lower().strip()
    kind = _CHANNEL_KIND.get(channel)
    if kind is None:
        return {
            "sent": False,
            "reason": "unknown_channel",
            "message": f"Unknown channel '{channel}'. Use email, slack, or gmail.",
        }

    # Resolve the recommendation, run, and account to act on.
    rec = recommendation if isinstance(recommendation, dict) and recommendation else None
    resolved_run_id = run_id
    if rec is None:
        if run_id:
            run = _find_run(run_id, org_id)
            if run is None:
                return {
                    "sent": False,
                    "reason": "run_not_found",
                    "channel": channel,
                    "message": f"Run {run_id} was not found for your org.",
                }
        else:
            runs = _org_runs(org_id)
            if account_id:
                aid = account_id.upper()
                runs = [r for r in runs if (r.get("account_id") or "").upper() == aid]
            run = next((r for r in runs if r.get("recommendation")), runs[0] if runs else None)
            if run is None:
                return {
                    "sent": False,
                    "reason": "no_run",
                    "channel": channel,
                    "message": "No recent run found. Run an NBA decision first, then ask me to send it.",
                }
        rec = run.get("recommendation")
        resolved_run_id = run.get("run_id")
        account_id = account_id or run.get("account_id")

    if not rec:
        return {
            "sent": False,
            "reason": "no_recommendation",
            "channel": channel,
            "run_id": resolved_run_id,
            "message": "That run has no recommendation yet. Run the decision to completion first.",
        }
    account_id = account_id or rec.get("account_id")

    # Email always sends over SES from the fixed platform sender (no connector
    # needed). Only Slack requires a configured connector.
    connector: Optional[Dict[str, Any]] = None
    if kind == "slack":
        try:
            from app.repositories import connectors as conn_repo

            connector = await conn_repo.get(org_id, "slack")
        except Exception:  # noqa: BLE001 - connectors slice optional
            connector = None
        if not _connector_ready("slack", connector):
            return {
                "sent": False,
                "reason": "slack_not_configured",
                "needs_connector": "slack",
                "channel": channel,
                "run_id": resolved_run_id,
                "message": _connect_hint("slack"),
            }

    # Generate the artifact, then deliver it.
    artifact_type = "slack" if kind == "slack" else "email"
    gen = await execute_action(
        artifact_type=artifact_type, recommendation=rec, account_id=account_id
    )
    if isinstance(gen, dict) and gen.get("error"):
        return {
            "sent": False,
            "reason": "generation_failed",
            "channel": channel,
            "run_id": resolved_run_id,
            "detail": gen["error"],
        }
    artifact = gen.get("artifact", {}) if isinstance(gen, dict) else {}

    if kind == "slack":
        config = (connector or {}).get("config") or {}
        text = artifact.get("message") or artifact.get("body") or ""
        result = _send_slack(config.get("webhook_url"), text)
        meta: Dict[str, Any] = {"channel": "slack", "preview": text[:280]}
    else:  # email / gmail / google all send via SES
        from app.config import settings

        recipient = to or _recipient(account_id)
        subject = artifact.get("subject", "")
        body = artifact.get("body", "")
        result = _send_email(recipient, subject, body, settings.ses_sender_email)
        meta = {"channel": "email", "to": recipient, "subject": subject}

    out: Dict[str, Any] = {
        **meta,
        "run_id": resolved_run_id,
        "account_id": account_id,
        "artifact": artifact,
    }
    out.update(result if isinstance(result, dict) else {"sent": False})
    return out


async def ingest_interaction(
    text: str,
    source_type: str = "document",
    account_id: Optional[str] = None,
    domain: str = "customer_success",
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest a raw interaction so it becomes citeable, retrievable evidence."""

    from fastapi import HTTPException

    from app.api.ingest import IngestIn
    from app.api.ingest import ingest as _ingest

    body = IngestIn(
        text=text,
        source_type=source_type,
        title=title,
        account_id=account_id,
        domain=domain,
    )
    try:
        return await _ingest(body)
    except HTTPException as exc:
        return {"error": exc.detail}


async def get_learning() -> Dict[str, Any]:
    """Return the learning loop surface: acceptance rate, trend, before/after."""

    from app.api.learning import get_learning as _get_learning

    return await _get_learning()


async def get_eval() -> Dict[str, Any]:
    """Return the evaluation suites and the headline business outcome."""

    from app.api.eval import get_eval as _get_eval

    return await _get_eval(refresh=False)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
TOOLS: Dict[str, Tool] = {
    "list_accounts": Tool(
        name="list_accounts",
        description=(
            "List the triage inbox of accounts, highest risk first. Use for "
            "questions like 'show me the riskiest accounts' or 'which accounts "
            "need attention'. Optionally scope to a single domain."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional domain key to scope the inbox.",
                }
            },
            "required": [],
        },
        run=list_accounts,
    ),
    "get_account": Tool(
        name="get_account",
        description="Get the full 360 view for one account by its id (e.g. ACC-1001).",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Account id, e.g. ACC-1001."}
            },
            "required": ["account_id"],
        },
        run=get_account,
    ),
    "list_domains": Tool(
        name="list_domains",
        description=(
            "List the available domain packs (the reusable verticals). Use for "
            "'what domains are available' or 'which verticals are supported'."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        run=list_domains,
    ),
    "get_domain": Tool(
        name="get_domain",
        description="Get the full configuration of one domain pack by key.",
        parameters={
            "type": "object",
            "properties": {
                "domain_key": {"type": "string", "description": "Domain pack key."}
            },
            "required": ["domain_key"],
        },
        run=get_domain,
    ),
    "run_nba": Tool(
        name="run_nba",
        description=(
            "Run the Next Best Action decision pipeline for an account given a "
            "signal. Returns an explainable, confidence-scored recommendation. "
            "Use for 'what should we do for ACC-1001' or 'recommend a next step'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Account id to act on."},
                "signal_text": {
                    "type": "string",
                    "description": "The triggering signal or situation text.",
                },
                "domain": {
                    "type": "string",
                    "description": "Domain pack key (default customer_success).",
                },
            },
            "required": ["account_id", "signal_text"],
        },
        run=run_nba,
    ),
    "search_knowledge": Tool(
        name="search_knowledge",
        description=(
            "Search the knowledge base and return grounding chunks with "
            "span-exact citations. Use for 'what do we know about X' or to find "
            "evidence. Optionally scope to one account."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "account_id": {
                    "type": "string",
                    "description": "Optional account id to scope the search.",
                },
                "domain": {"type": "string", "description": "Domain pack key."},
                "k": {"type": "integer", "description": "Max results (default 5)."},
            },
            "required": ["query"],
        },
        run=search_knowledge,
    ),
    "evaluate_policy": Tool(
        name="evaluate_policy",
        description=(
            "Evaluate a recommendation against a domain's policy gates and return "
            "pass/warn/fail results plus whether approval is required."
        ),
        parameters={
            "type": "object",
            "properties": {
                "recommendation": {
                    "type": "object",
                    "description": "The recommendation object to check.",
                },
                "domain": {"type": "string", "description": "Domain pack key."},
                "account_id": {"type": "string", "description": "Optional account id."},
            },
            "required": ["recommendation"],
        },
        run=evaluate_policy,
    ),
    "execute_action": Tool(
        name="execute_action",
        description=(
            "Generate a concrete artifact from a recommendation: an email, a "
            "crm_task, or a slack handoff. Pass a run_id or an inline "
            "recommendation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "artifact_type": {
                    "type": "string",
                    "enum": ["email", "crm_task", "slack"],
                    "description": "The artifact to generate.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Id of a prior run to pull the recommendation from.",
                },
                "recommendation": {
                    "type": "object",
                    "description": "Inline recommendation if no run_id is given.",
                },
                "account_id": {"type": "string", "description": "Optional account id."},
            },
            "required": ["artifact_type"],
        },
        run=execute_action,
    ),
    "get_last_run": Tool(
        name="get_last_run",
        description=(
            "Get the org's most recent run and its stored recommendation. Use "
            "when the user references 'my last run', 'the last recommendation', "
            "or wants to act on the latest decision. Optionally scope to one "
            "account."
        ),
        parameters={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Optional account id to find that account's latest run.",
                }
            },
            "required": [],
        },
        run=get_last_run,
    ),
    "get_run": Tool(
        name="get_run",
        description=(
            "Get one specific run (and its recommendation) by run id, scoped to "
            "the caller's org."
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run id to fetch."}
            },
            "required": ["run_id"],
        },
        run=get_run,
    ),
    "send_artifact": Tool(
        name="send_artifact",
        description=(
            "Send a run's recommendation to a channel. Channel 'email' always "
            "sends over Amazon SES from the platform sender (no setup needed); "
            "'slack' posts via the org's incoming webhook (must be connected in "
            "Settings). Resolves the recommendation from an inline object, a "
            "run_id, or the org's most recent run, generates the artifact, and "
            "delivers it. Pass 'to' to email a specific address; otherwise it "
            "uses the account's contact. Use for 'email the latest run to "
            "someone@x.com' or 'send the Northwind play to slack'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": ["email", "slack", "gmail"],
                    "description": "Where to send: email (SES) or slack.",
                },
                "to": {
                    "type": "string",
                    "description": "Optional explicit email recipient address.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional run id; defaults to the org's most recent run.",
                },
                "recommendation": {
                    "type": "object",
                    "description": "Optional inline recommendation instead of a run.",
                },
                "account_id": {
                    "type": "string",
                    "description": "Optional account id (recipient / run filter).",
                },
            },
            "required": ["channel"],
        },
        run=send_artifact,
    ),
    "tag_run": Tool(
        name="tag_run",
        description=(
            "Associate a run with an account and/or a free-text note. Defaults "
            "to the org's most recent run when no run_id is given."
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Optional run id; defaults to the most recent run.",
                },
                "account_id": {"type": "string", "description": "Account to associate."},
                "note": {"type": "string", "description": "Optional free-text note."},
            },
            "required": [],
        },
        run=tag_run,
    ),
    "ingest_interaction": Tool(
        name="ingest_interaction",
        description=(
            "Ingest raw interaction text (note, transcript, email, CRM rows) so "
            "it becomes citeable, retrievable evidence for the next decision."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The raw interaction text."},
                "source_type": {
                    "type": "string",
                    "description": "Source type key (default document).",
                },
                "account_id": {"type": "string", "description": "Optional account to scope to."},
                "domain": {"type": "string", "description": "Domain pack key."},
                "title": {"type": "string", "description": "Optional human title."},
            },
            "required": ["text"],
        },
        run=ingest_interaction,
    ),
    "get_learning": Tool(
        name="get_learning",
        description=(
            "Read the learning loop surface: acceptance rate, the acceptance "
            "trend, recent decided episodes, and the projected NRR before/after."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        run=get_learning,
    ),
    "get_eval": Tool(
        name="get_eval",
        description="Read the evaluation suites and the headline business outcome.",
        parameters={"type": "object", "properties": {}, "required": []},
        run=get_eval,
    ),
}


def openai_tools() -> List[Dict[str, Any]]:
    """Return all tools in the OpenAI ``tools`` schema for LLM tool-calling."""

    return [tool.to_openai() for tool in TOOLS.values()]


async def run_tool(name: str, args: Optional[Dict[str, Any]] = None) -> Any:
    """Execute a registered tool by name with a dict of arguments.

    Unknown tools and bad arguments return an error dict rather than raising, so
    the agent loop can surface the problem to the user and keep going.
    """

    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return await tool.run(**(args or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - keep the agent resilient
        return {"error": f"{name} failed: {exc}"}
