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
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi.concurrency import run_in_threadpool


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

    accounts = await _list_accounts(domain=domain, org_id=current_org_id())
    return {"count": len(accounts), "accounts": accounts}


async def get_account(account_id: str) -> Dict[str, Any]:
    """Return the account 360 (profile, signals, history, documents)."""

    from fastapi import HTTPException

    from app.api.accounts import get_account as _get_account

    try:
        return await _get_account(account_id, org_id=current_org_id())
    except HTTPException as exc:
        return {"error": exc.detail, "account_id": account_id}


async def list_domains() -> Dict[str, Any]:
    """Return every domain pack on disk (the reusable verticals)."""

    from app.api.domains import get_domains as _get_domains

    packs = await _get_domains(org_id=current_org_id())
    return {"count": len(packs), "domains": packs}


async def get_domain(domain_key: str) -> Dict[str, Any]:
    """Return the full parsed pack for one domain."""

    from fastapi import HTTPException

    from app.api.domains import get_domain as _get_domain

    try:
        return await _get_domain(domain_key, org_id=current_org_id())
    except HTTPException as exc:
        return {"error": exc.detail, "domain_key": domain_key}


async def _resolve_org_account(org_id: str, ref: str) -> Optional[str]:
    """Resolve an account reference (id OR name) to an id owned by ``org_id``.

    Returns None when the workspace has no such account, so a run never lands on
    an account the caller does not own (e.g. the LLM guessing a demo id), and a
    name like "Halcyon" maps to its real id.
    """

    if not ref:
        return None
    try:
        from app.api.accounts import _org_accounts

        accounts = await _org_accounts(org_id, None)
    except Exception:  # noqa: BLE001 - accounts slice optional
        return None
    ref_l = str(ref).strip().lower()
    by_id = [a for a in accounts if str(a.get("account_id", "")).lower() == ref_l]
    if by_id:
        return by_id[0].get("account_id")
    by_name = [a for a in accounts if str(a.get("name", "")).lower() == ref_l]
    if by_name:
        return by_name[0].get("account_id")
    contains = [a for a in accounts if ref_l and ref_l in str(a.get("name", "")).lower()]
    if contains:
        return contains[0].get("account_id")
    return None


async def run_nba(
    account_id: str,
    signal_text: str,
    domain: str = "customer_success",
) -> Dict[str, Any]:
    """Run the full LangGraph NBA pipeline and return the recommendation.

    Drives the same planner graph the runs API streams, but synchronously to a
    final state. The run is registered in the runs registry so a follow-up
    ``execute_action`` can reference it by ``run_id``. ``account_id`` may be an
    account id OR a name (e.g. "Halcyon"); it is resolved against the caller's
    workspace and rejected if the account is not theirs.
    """

    from app.api.runs import _RUNS
    from app.deps import get_checkpointer
    from app.graph.planner import build_graph
    from app.packs.loader import (
        reset_pack_org,
        reset_roster_overrides,
        set_pack_org,
        set_roster_overrides,
    )
    from app.repositories import org_packs as org_packs_repo
    from app.repositories import pack_overrides as overrides_repo

    org_id = current_org_id()
    resolved = await _resolve_org_account(org_id, account_id)
    if resolved is None:
        return {
            "error": f"account not found in your workspace: {account_id}",
            "account_id": account_id,
        }
    account_id = resolved

    # Resolve the account's display name so the drafter/recommendation refer to
    # it by NAME (e.g. "Halcyon Fitness"), never the internal id (ACC-...).
    account_ctx: Dict[str, Any] = {}
    account_name = account_id
    try:
        from app.api.accounts import _org_account

        acct = await _org_account(org_id, account_id)
        if isinstance(acct, dict) and not acct.get("error"):
            account_ctx = acct
            account_name = acct.get("name") or account_name
    except Exception:  # noqa: BLE001 - name is best effort
        pass

    run_id = str(uuid.uuid4())
    signal = {"type": "", "content": signal_text}
    initial_state: Dict[str, Any] = {
        "run_id": run_id,
        "org_id": org_id,
        "domain": domain,
        "account_id": account_id,
        "account_name": account_name,
        "account": account_ctx,
        "signal": signal,
        "plan": [],
        "capabilities": [],
        "steps": [],
        "messages": [],
        "recommendation": None,
    }
    config = {"configurable": {"thread_id": run_id}}

    # Bind the caller's org so the graph resolves THIS org's uploaded domain pack
    # (never another tenant's) when the copilot runs a decision on a new domain.
    try:
        await org_packs_repo.hydrate_loader(org_id)
    except Exception:  # noqa: BLE001 - hydration is best effort
        pass

    # Honor the org's Workflow Studio roster overrides for this run.
    roster_overrides: Dict[str, Any] = {}
    try:
        blob = await overrides_repo.get_overrides(org_id, domain)
        roster_overrides = (blob or {}).get("rosters") or {}
    except Exception:  # noqa: BLE001 - overrides are best effort
        pass

    checkpointer = await get_checkpointer()
    graph = build_graph(checkpointer)
    token = set_pack_org(org_id)
    roster_token = set_roster_overrides(roster_overrides)
    try:
        final = await graph.ainvoke(initial_state, config=config)
    finally:
        reset_roster_overrides(roster_token)
        reset_pack_org(token)

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
    # Scope retrieval to the caller's org so a non-demo user sees only their own
    # plus shared seed evidence, never another tenant's ingested knowledge.
    evidence = await retriever.search(
        query, account_id=account_id, k=k, org_id=current_org_id()
    )

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
        # Pass the authenticated org explicitly: calling the route function
        # directly bypasses FastAPI's dependency resolution, and the endpoint is
        # org-scoped so a client-supplied run_id never crosses the tenant line.
        out = await _execute(body, org_id=current_org_id())
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


def _episode_runs(org_id: str) -> List[Dict[str, Any]]:
    """Durable runs derived from persisted episodes.

    The in-memory ``_RUNS`` registry is wiped on every restart, so a follow-up
    like "email the last run" would lose the user's real decision (and resolve
    the wrong account). Episodes are durable and org-scoped, so we surface them
    as runs too: this keeps the last-run lookup correct across restarts.
    """

    try:
        from app.api._org import DEMO_ORG
        from app.memory.store import get_memory

        episodes = get_memory().all_episodes()
    except Exception:  # noqa: BLE001 - memory slice optional
        return []

    out: List[Dict[str, Any]] = []
    for ep in episodes:
        ep_org = getattr(ep, "org_id", None) or DEMO_ORG
        if ep_org != org_id:
            continue
        out.append(
            {
                "run_id": getattr(ep, "id", None),
                "org_id": ep_org,
                "account_id": getattr(ep, "account_id", None),
                "domain": getattr(ep, "domain", None),
                "status": "finished",
                "recommendation": getattr(ep, "recommendation", None),
                "created_at": getattr(ep, "created_at", None),
                "episode_id": getattr(ep, "id", None),
            }
        )
    return out


def _org_runs(org_id: str) -> List[Dict[str, Any]]:
    """Return the org's runs (live in-memory plus durable episode runs), recent first."""

    live = [r for r in _all_runs().values() if r.get("org_id") == org_id]
    seen = {r.get("episode_id") for r in live if r.get("episode_id")}
    durable = [r for r in _episode_runs(org_id) if r.get("episode_id") not in seen]
    runs = live + durable
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


async def _account_contact_emails(
    org_id: str, account_id: Optional[str]
) -> List[str]:
    """Return every SAVED contact email for an account, in saved order.

    This is how 'email all contacts of <account>' resolves its recipients: the
    org's own contacts linked to the account (``contacts_repo.list_for_account``),
    never the account OWNER (the owner is a CSM name, not a customer recipient).
    Contacts without a valid email are skipped so a name can never reach SES.
    """

    if not account_id:
        return []
    try:
        from app.repositories import contacts as contacts_repo
        from app.services.email import is_valid_email
    except Exception:  # noqa: BLE001 - contacts / email slice optional offline
        return []
    try:
        rows = await contacts_repo.list_for_account(org_id, account_id)
    except Exception:  # noqa: BLE001 - degrade gracefully when unavailable
        return []
    out: List[str] = []
    for row in rows:
        email = (row.get("email") or "").strip()
        if email and is_valid_email(email):
            out.append(email)
    return out


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


async def _resolve_contact(org_id: str, contact: str) -> Optional[Dict[str, Any]]:
    """Resolve a saved contact by name or email within the org (best-effort)."""

    try:
        from app.repositories import contacts as contacts_repo

        return await contacts_repo.find_by_name_or_email(org_id, contact)
    except Exception:  # noqa: BLE001 - contacts slice optional / offline
        return None


def _split_addresses(value: Optional[str]) -> List[str]:
    """Split a free-text address field into individual addresses.

    Lets the copilot pass several addresses in one ``to`` string (comma,
    semicolon, or whitespace separated), e.g. 'ops@x.com, lead@x.com'.
    """

    if not value:
        return []
    parts = value.replace(";", ",").replace("\n", ",").split(",")
    out: List[str] = []
    for part in parts:
        for token in part.split():
            token = token.strip()
            if token:
                out.append(token)
    return out


async def send_artifact(
    channel: str = "email",
    run_id: Optional[str] = None,
    recommendation: Optional[Dict[str, Any]] = None,
    account_id: Optional[str] = None,
    to: Optional[str] = None,
    contact: Optional[str] = None,
    contacts: Optional[List[str]] = None,
    recipients: Optional[List[str]] = None,
    all_account_contacts: Optional[bool] = None,
) -> Dict[str, Any]:
    """Send a run's recommendation to a channel using the org's connectors.

    Resolves the recommendation (inline, by ``run_id``, or the org's most
    recent run), generates the matching artifact (email or Slack message), and
    delivers it through the org's configured connector. For email it can fan out
    to several people at once: pass any number of saved contacts (``contact`` /
    ``contacts``, by name or email) plus any number of explicit addresses
    (``to`` / ``recipients``), and it sends to each so the copilot can 'email the
    play to ops@x.com and the account contact'.

    EMAIL ALL OF AN ACCOUNT'S CONTACTS: to 'email the play to all contacts of
    <account>', pass ``account_id`` and set ``all_account_contacts`` true (this
    is also the default when no explicit recipient is given). It resolves the
    account's SAVED contacts and emails every one of them. It NEVER uses the
    account owner name as an address; contacts without a valid email are skipped;
    if the account has no contacts it returns ``reason='no_contacts'`` instead of
    guessing.

    Refuses (never raises) when the channel is not connected, telling the user to
    connect it in Settings. This is the same send path the execute API uses.
    """

    org_id = current_org_id()
    # Resolve every saved contact (single ``contact`` plus the ``contacts`` list)
    # to an address up front so 'email the recommendation to Dana and ops@x.com'
    # targets the saved person and the literal address.
    contact_emails: List[str] = []
    contact_queries = list(contacts or [])
    if contact:
        contact_queries.append(contact)
    # A SPECIFIC named recipient that does not resolve must not silently become a
    # broadcast to the whole account. We only fan out for explicit "all/every/
    # account contacts" phrasing, not for an unknown name.
    unresolved_names: List[str] = []
    for query in contact_queries:
        q = str(query).strip()
        # A literal email address can be sent to directly without a lookup.
        if "@" in q:
            contact_emails.append(q)
            continue
        resolved = await _resolve_contact(org_id, query)
        if resolved is None:
            low = q.lower()
            is_fanout_phrase = any(
                w in low for w in ("all", "every", "everyone", "contacts", "team")
            )
            if not is_fanout_phrase:
                # A specific name that does not match a saved contact: record it
                # so we ask instead of emailing everyone.
                unresolved_names.append(q)
            continue
        if resolved.get("email"):
            contact_emails.append(str(resolved["email"]))
        account_id = account_id or resolved.get("account_id")
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

    # The senders below use synchronous HTTP / boto3 clients; offload them so a
    # slow Slack or SES round-trip never blocks the event loop (offline / no-creds
    # paths return before any network).
    if kind == "slack":
        config = (connector or {}).get("config") or {}
        text = artifact.get("message") or artifact.get("body") or ""
        result = await run_in_threadpool(_send_slack, config.get("webhook_url"), text)
        meta: Dict[str, Any] = {"channel": "slack", "preview": text[:280]}
    else:  # email / gmail / google all send via SES
        from app.config import settings

        # Explicit recipients the caller named: resolved saved contacts
        # (``contact`` / ``contacts``), the ``recipients`` list, and a possibly
        # multi-address ``to``.
        explicit = list(contact_emails)
        explicit.extend(recipients or [])
        explicit.extend(_split_addresses(to))

        # A specific name was given that does not match a saved contact: ask,
        # do NOT silently email the whole account.
        if unresolved_names and not explicit and not all_account_contacts:
            names = ", ".join(unresolved_names)
            return {
                "sent": False,
                "reason": "contact_not_found",
                "channel": channel,
                "run_id": resolved_run_id,
                "message": (
                    f"No saved contact matches '{names}'. Add them on the Contacts "
                    "page, or give me an email address. I will not email the whole "
                    "account or guess an address."
                ),
            }

        # When no explicit recipient is given, or the caller asked to email the
        # whole account, fan out to EVERY saved contact of the account. We never
        # fall back to the account owner name (which is not an email address).
        fan_all = bool(all_account_contacts) or not explicit
        account_emails: List[str] = []
        if fan_all:
            account_emails = await _account_contact_emails(org_id, account_id)

        # Dedupe case-insensitively, preserving order (explicit first).
        seen: set[str] = set()
        addresses: List[str] = []
        for addr in [*explicit, *account_emails]:
            clean = (addr or "").strip()
            if not clean or clean.lower() in seen:
                continue
            seen.add(clean.lower())
            addresses.append(clean)

        if not addresses:
            # Asked to email the account's contacts but it has none: say so
            # plainly instead of guessing the owner name.
            if fan_all and account_id:
                return {
                    "sent": False,
                    "reason": "no_contacts",
                    "channel": channel,
                    "run_id": resolved_run_id,
                    "account_id": account_id,
                    "message": (
                        f"{account_id} has no saved contacts with an email. Add "
                        "contacts on the Contacts page, or give me an address."
                    ),
                }
            return {
                "sent": False,
                "reason": "no_recipient",
                "channel": channel,
                "run_id": resolved_run_id,
                "account_id": account_id,
                "message": (
                    "No recipient to email. Give me an address, or an account "
                    "with saved contacts."
                ),
            }

        subject = artifact.get("subject", "")
        body = artifact.get("body", "")
        # Map each address back to its EXACT saved contact name so the assistant
        # reports real names instead of guessing one from the email address.
        name_by_email: Dict[str, str] = {}
        if account_id:
            try:
                from app.repositories import contacts as contacts_repo

                for c in await contacts_repo.list_for_account(org_id, account_id):
                    em = str(c.get("email") or "").strip().lower()
                    if em and c.get("name"):
                        name_by_email[em] = str(c["name"])
            except Exception:  # noqa: BLE001 - names are best effort
                pass
        per: List[Dict[str, Any]] = []
        for addr in addresses:
            one = await run_in_threadpool(
                _send_email, addr, subject, body, settings.ses_sender_email
            )
            per.append(
                {
                    "to": addr,
                    "name": name_by_email.get(addr.strip().lower()),
                    "sent": bool(one.get("sent")),
                    "reason": one.get("reason"),
                    "detail": one.get("detail") or one.get("message_id"),
                }
            )
        if not per:
            result = {"sent": False, "reason": "no_recipient"}
        else:
            sent_any = any(p["sent"] for p in per)
            result = {
                "sent": sent_any,
                "reason": None
                if sent_any
                else next((p["reason"] for p in per if p["reason"]), None),
                "results": per,
            }
        to_line = ", ".join(p["to"] for p in per) or None
        meta = {"channel": "email", "to": to_line, "subject": subject}

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
        return await _ingest(body, org_id=current_org_id())
    except HTTPException as exc:
        return {"error": exc.detail}


async def get_learning() -> Dict[str, Any]:
    """Return the learning loop surface: acceptance rate, trend, before/after."""

    from app.api.learning import get_learning as _get_learning

    return await _get_learning(org_id=current_org_id())


async def get_eval() -> Dict[str, Any]:
    """Return the evaluation suites and the headline business outcome."""

    from app.api.eval import get_eval as _get_eval

    return await _get_eval(refresh=False, org_id=current_org_id())


async def web_search(query: str, k: int = 6) -> Dict[str, Any]:
    """Live Google web search via Serper. Returns title/snippet/link results.

    Lets the copilot pull fresh public context (company news, market signals,
    background on an account) and reason over it. Degrades to an empty result
    with a clear reason when SERPER_API_KEY is not configured.
    """
    from app.config import settings
    from app.retrieval.connectors.web_search import serper_search

    q = (query or "").strip()
    if not q:
        return {"error": "empty query", "results": []}
    if not settings.serper_api_key:
        return {"error": "web search not configured (set SERPER_API_KEY)", "results": []}
    results = await serper_search(q, num=max(1, min(int(k or 6), 10)))
    return {"query": q, "count": len(results), "results": results}


async def send_message(to: str, subject: str, body: str) -> Dict[str, Any]:
    """Send a COMPOSED email (your own subject + body text) to a person.

    Use this to send arbitrary written content (a summary, a comparison, a note)
    to someone. This is NOT for delivering a run's recommendation: use
    send_artifact for that. The recipient must be a saved contact (by name) or an
    email address the user gave; never invent one.
    """
    from app.config import settings
    from app.services.email import is_valid_email

    org_id = current_org_id()
    recipient = (to or "").strip()
    if not recipient:
        return {
            "sent": False,
            "reason": "no_recipient",
            "message": "Tell me who to send to: a saved contact name or an email address.",
        }

    addr: Optional[str] = None
    name: Optional[str] = None
    if "@" in recipient:
        addr = recipient
    else:
        resolved = await _resolve_contact(org_id, recipient)
        if resolved and resolved.get("email"):
            addr, name = str(resolved["email"]), resolved.get("name")

    if not addr or not is_valid_email(addr):
        return {
            "sent": False,
            "reason": "contact_not_found",
            "message": (
                f"No saved contact or valid email for '{to}'. Add the contact on the "
                "Contacts page, or give me their email address. I will not guess one."
            ),
        }

    result = await run_in_threadpool(
        _send_email, addr, subject or "(no subject)", body or "", settings.ses_sender_email
    )
    return {
        "sent": bool(result.get("sent")),
        "to": addr,
        "name": name,
        "subject": subject,
        "reason": result.get("reason"),
    }


async def create_account(
    name: str,
    domain: str = "customer_success",
    industry: Optional[str] = None,
    segment: Optional[str] = None,
    arr: Optional[float] = None,
    health_score: Optional[float] = None,
    risk_level: Optional[str] = None,
    owner: Optional[str] = None,
    signals: Optional[List[Any]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an account in the caller's workspace (notes are ingested as evidence)."""
    from fastapi import HTTPException

    from app.api.accounts import AccountIn
    from app.api.accounts import create_account as _create

    if not (name or "").strip():
        return {"created": False, "error": "name is required"}
    try:
        body = AccountIn(
            name=name,
            domain=domain or "customer_success",
            industry=industry,
            segment=segment,
            arr=arr,
            health_score=health_score,
            risk_level=risk_level,
            owner=owner,
            signals=signals or None,
            notes=notes,
        )
        out = await _create(body, org_id=current_org_id())
        return {"created": True, "account": out}
    except HTTPException as exc:
        return {"created": False, "error": exc.detail}


async def list_contacts(account_id: Optional[str] = None) -> Dict[str, Any]:
    """List saved contacts, optionally scoped to one account."""
    from app.repositories import contacts as contacts_repo

    org_id = current_org_id()
    if account_id:
        resolved = await _resolve_org_account(org_id, account_id) or account_id
        rows = await contacts_repo.list_for_account(org_id, resolved)
    else:
        rows = await contacts_repo.list_for_org(org_id)
    return {
        "contacts": [
            {
                "name": c.get("name"),
                "email": c.get("email"),
                "account_id": c.get("account_id"),
                "role": c.get("role"),
            }
            for c in rows
        ],
        "count": len(rows),
    }


async def add_contact(
    name: str, email: str, account_id: Optional[str] = None, role: Optional[str] = None
) -> Dict[str, Any]:
    """Save a contact (name + email) to the workspace, optionally tied to an account."""
    from app.repositories import contacts as contacts_repo
    from app.services.email import is_valid_email

    if not is_valid_email(email):
        return {"added": False, "error": f"'{email}' is not a valid email address"}
    org_id = current_org_id()
    resolved = await _resolve_org_account(org_id, account_id) if account_id else None
    c = await contacts_repo.upsert(
        org_id, name=(name or "").strip(), email=email.strip(), account_id=resolved, role=role
    )
    return {
        "added": True,
        "contact": {"name": c.get("name"), "email": c.get("email"), "account_id": c.get("account_id")},
    }


async def list_runs(account_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    """List the org's recent NBA runs, optionally for one account."""
    org_id = current_org_id()
    runs = _org_runs(org_id)
    if account_id:
        resolved = await _resolve_org_account(org_id, account_id) or account_id
        runs = [r for r in runs if str(r.get("account_id") or "").upper() == str(resolved).upper()]
    out = []
    for r in runs[: max(1, min(int(limit or 10), 50))]:
        rec = r.get("recommendation") or {}
        out.append(
            {
                "run_id": r.get("run_id"),
                "account_id": r.get("account_id"),
                "action": (rec.get("action") or {}).get("title"),
                "confidence": (rec.get("confidence") or {}).get("score"),
                "created_at": r.get("created_at"),
            }
        )
    return {"runs": out, "count": len(out)}


async def update_account(
    account_id: str,
    name: Optional[str] = None,
    industry: Optional[str] = None,
    segment: Optional[str] = None,
    arr: Optional[float] = None,
    health_score: Optional[float] = None,
    risk_level: Optional[str] = None,
    owner: Optional[str] = None,
    renewal_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Update fields on an existing account (only the fields you pass change)."""
    from fastapi import HTTPException

    from app.api.accounts import AccountUpdate
    from app.api.accounts import update_account as _update

    org_id = current_org_id()
    resolved = await _resolve_org_account(org_id, account_id)
    if resolved is None:
        return {"updated": False, "error": f"account not found: {account_id}"}
    try:
        body = AccountUpdate(
            name=name,
            industry=industry,
            segment=segment,
            arr=arr,
            health_score=health_score,
            risk_level=risk_level,
            owner=owner,
            renewal_date=renewal_date,
        )
        out = await _update(resolved, body, org_id=org_id)
        return {"updated": True, "account": out}
    except HTTPException as exc:
        return {"updated": False, "error": exc.detail}


async def get_timeline(account_id: str) -> Dict[str, Any]:
    """Return one account's newest-first audit timeline (interactions, runs, decisions)."""
    from app.api.accounts import get_account_timeline as _tl

    org_id = current_org_id()
    resolved = await _resolve_org_account(org_id, account_id)
    if resolved is None:
        return {"error": f"account not found: {account_id}"}
    return await _tl(resolved, org_id=org_id)


async def get_integrations() -> Dict[str, Any]:
    """Return the org's connector status (email/SES, Slack, Google)."""
    from app.api.integrations import list_integrations as _li

    return await _li(org_id=current_org_id())


async def record_outcome(
    episode_id: str, decision: str, reason: Optional[str] = None
) -> Dict[str, Any]:
    """Record a run's outcome (accepted / rejected / edited) into the learning loop."""
    from fastapi import HTTPException

    from app.api.learning import OutcomeIn
    from app.api.learning import record_learning_outcome as _ro

    try:
        body = OutcomeIn(episode_id=episode_id, decision=decision, reason=reason)
        return await _ro(body, org_id=current_org_id())
    except HTTPException as exc:
        return {"error": exc.detail}


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
    "web_search": Tool(
        name="web_search",
        description=(
            "Search the EXTERNAL public web (Google via Serper) for information "
            "that is NOT in this workspace: general market news, public company "
            "background, industry trends. Returns title, snippet, and link. This "
            "is a SECONDARY source: for anything about an account or company in "
            "the workspace ('their context', 'what do we know about X'), use "
            "search_knowledge and get_account FIRST to read the user's ingested "
            "data, and only use web_search to add external public context on top. "
            "Never use web_search in place of the account's own ingested evidence. "
            "Cite the links you use."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Web search query."},
                "k": {"type": "integer", "description": "Max results (default 6, max 10)."},
            },
            "required": ["query"],
        },
        run=web_search,
    ),
    "send_message": Tool(
        name="send_message",
        description=(
            "Send a COMPOSED email (your own subject and body) to a person, for "
            "arbitrary content like a summary, comparison, or note the user asked "
            "you to send. This is NOT for a run's recommendation (use send_artifact "
            "for that). 'to' is a saved contact NAME or an email the user gave; "
            "never invent a recipient. Put the actual content the user asked to "
            "send in 'body', not a generic message."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Saved contact name or an email address the user provided."},
                "subject": {"type": "string", "description": "Email subject."},
                "body": {"type": "string", "description": "The exact content to send."},
            },
            "required": ["to", "subject", "body"],
        },
        run=send_message,
    ),
    "create_account": Tool(
        name="create_account",
        description=(
            "Create a new account in the user's workspace. Provide the name and "
            "domain (customer_success, collections, saas_sales); optionally "
            "industry, segment, arr, health_score, risk_level, owner, signals, and "
            "notes (notes are ingested as retrievable evidence). Use when the user "
            "asks to add or create an account."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Account / company name."},
                "domain": {"type": "string", "description": "Domain pack key (default customer_success)."},
                "industry": {"type": "string"},
                "segment": {"type": "string"},
                "arr": {"type": "number", "description": "Annual recurring revenue."},
                "health_score": {"type": "number", "description": "0 to 100."},
                "risk_level": {"type": "string", "description": "critical / high / medium / low."},
                "owner": {"type": "string", "description": "Account owner / CSM."},
                "signals": {"type": "array", "items": {"type": "string"}, "description": "Active signal keys."},
                "notes": {"type": "string", "description": "Free-text context, ingested as evidence."},
            },
            "required": ["name"],
        },
        run=create_account,
    ),
    "list_contacts": Tool(
        name="list_contacts",
        description="List saved contacts, optionally for one account (pass account_id or name).",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Optional account id or name to scope to."},
            },
        },
        run=list_contacts,
    ),
    "add_contact": Tool(
        name="add_contact",
        description=(
            "Save a contact (name + a valid email) to the workspace, optionally "
            "tied to an account. Use when the user asks to add or save a contact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string", "description": "A valid email address."},
                "account_id": {"type": "string", "description": "Optional account id or name."},
                "role": {"type": "string"},
            },
            "required": ["name", "email"],
        },
        run=add_contact,
    ),
    "list_runs": Tool(
        name="list_runs",
        description="List the org's recent NBA runs (run id, account, action, confidence), optionally for one account.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Optional account id or name to scope to."},
                "limit": {"type": "integer", "description": "Max runs (default 10)."},
            },
        },
        run=list_runs,
    ),
    "update_account": Tool(
        name="update_account",
        description="Update fields on an existing account (name, industry, segment, arr, health_score, risk_level, owner, renewal_date). Only the fields you pass change.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Account id or name."},
                "name": {"type": "string"},
                "industry": {"type": "string"},
                "segment": {"type": "string"},
                "arr": {"type": "number"},
                "health_score": {"type": "number"},
                "risk_level": {"type": "string"},
                "owner": {"type": "string"},
                "renewal_date": {"type": "string"},
            },
            "required": ["account_id"],
        },
        run=update_account,
    ),
    "get_timeline": Tool(
        name="get_timeline",
        description="Return one account's newest-first audit timeline (interactions, runs, decisions, outcomes).",
        parameters={
            "type": "object",
            "properties": {"account_id": {"type": "string", "description": "Account id or name."}},
            "required": ["account_id"],
        },
        run=get_timeline,
    ),
    "get_integrations": Tool(
        name="get_integrations",
        description="Return the org's connector status (email/SES, Slack, Google). Use to answer 'is Slack connected'.",
        parameters={"type": "object", "properties": {}},
        run=get_integrations,
    ),
    "record_outcome": Tool(
        name="record_outcome",
        description="Record a run's outcome into the learning loop. episode_id from a run; decision is accepted, rejected, or edited.",
        parameters={
            "type": "object",
            "properties": {
                "episode_id": {"type": "string", "description": "The run's episode id."},
                "decision": {"type": "string", "description": "accepted / rejected / edited."},
                "reason": {"type": "string"},
            },
            "required": ["episode_id", "decision"],
        },
        run=record_outcome,
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
            "delivers it. Pass 'to' to email a specific address, or 'contact' / "
            "'contacts' to resolve saved people by name or email. To EMAIL ALL "
            "CONTACTS OF AN ACCOUNT (for example 'email the play to all contacts "
            "of Northwind' or 'email everyone at ACC-1001'), pass 'account_id' "
            "and set 'all_account_contacts' true: it emails every SAVED contact "
            "of that account and never uses the account owner name as an address. "
            "Use for 'email the latest run to someone@x.com', 'email the "
            "recommendation to Dana', 'email all contacts of ACC-1001', or 'send "
            "the Northwind play to slack'."
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
                "contact": {
                    "type": "string",
                    "description": (
                        "Optional saved contact to resolve the recipient by name "
                        "or email, e.g. 'Dana Lee' or 'dana@acme.com'."
                    ),
                },
                "contacts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of saved contacts (names or emails) to "
                        "email in one send."
                    ),
                },
                "recipients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of explicit email addresses.",
                },
                "all_account_contacts": {
                    "type": "boolean",
                    "description": (
                        "Set true to email EVERY saved contact of 'account_id' "
                        "(use for 'email all contacts of <account>'). Defaults to "
                        "on when no explicit recipient is given."
                    ),
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
