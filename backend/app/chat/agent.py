"""The conversational agent that drives the platform through its tools.

Two paths share one tool layer (``app.chat.tools``):

* ONLINE (an OpenAI key is configured): real multi-step tool-calling. The model
  is bound to the tool schemas, it picks tools, we execute them, feed the
  results back, and loop until the model produces a final answer.

* OFFLINE (DEMO_MODE or no key): a deterministic intent router maps the user
  message to the right tool(s) by keyword and regex, executes them, and composes
  a clear textual answer. This keeps the chat fully functional and testable with
  no network access.

Both paths are exposed as async generators that yield typed events
(``message``, ``tool.called``, ``tool.result``, ``final``) plus a non-streaming
``answer`` helper that collects the same trace.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from app.chat import tools as toolkit

# Hard cap on tool-calling iterations so a misbehaving model cannot loop forever.
_MAX_STEPS = 6

# Pacing for the offline (DEMO) path so the deterministic reply streams visibly
# without a key: a brief pause while a tool "runs" (called -> result) and a small
# gap between text chunks. Kept tiny so tests and the non-streaming path stay fast.
_TOOL_DELAY = 0.12
_CHUNK_DELAY = 0.02
_WORDS_PER_CHUNK = 3

_SYSTEM_PROMPT = (
    "You are the assistant for an Intelligent Next Best Action platform. You "
    "help users triage accounts, inspect domain packs, run explainable NBA "
    "decisions, search the knowledge base with citations, evaluate policy, "
    "generate artifacts, ingest interactions, and read the learning and eval "
    "surfaces. Use the provided tools to answer with real data instead of "
    "guessing. Be thorough and agentic: gather complete context across MULTIPLE "
    "tools before answering. For a question about a specific account, list or "
    "look it up, then enrich it (for example search_knowledge for supporting "
    "evidence, or run_nba for a recommendation) rather than stopping after one "
    "call. When you cite knowledge, mention the source ids. Format answers in "
    "clean markdown (headings, bold, lists, tables) and keep them grounded.\n\n"
    "GROUNDING ORDER (important): Questions about an account, a company in the "
    "workspace, or 'their context', 'what do we know about X', or 'tell me about "
    "X' are about the user's OWN ingested data. You MUST answer from internal "
    "tools first: list_accounts / get_account to find the account, and "
    "search_knowledge to read the ingested evidence (CRM notes, transcripts, "
    "emails, invoices) the user uploaded. Cite the source ids. web_search is ONLY "
    "for fresh PUBLIC/EXTERNAL information that is genuinely not in the workspace, "
    "and it NEVER replaces the account's own ingested context. Do not answer an "
    "account question with web results when the user has uploaded data for it.\n\n"
    "NO HALLUCINATION: Never invent, embellish, or guess any fact that is not "
    "present in a tool result. Report names, emails, numbers, ids, and "
    "recipients EXACTLY as the tools return them. Do NOT add or expand names "
    "(for example, do not turn a contact named 'Nihesh' into 'Nihesh Reddy', or "
    "derive a person's name from their email address). If a detail was not "
    "returned by a tool, do not state it. When you report who an email was sent "
    "to, list the exact addresses the send tool returned.\n\n"
    "ENTITY NOT FOUND: If a tool returns nothing for an account, contact, or run "
    "(for example list_accounts / get_account does not include the id the user "
    "named), the entity is NOT in the workspace. Say so plainly (for example 'I do "
    "not see ACC-1001 in your workspace; your accounts are ...'). NEVER write a "
    "generic, hypothetical, or 'fictional' answer about an account or entity the "
    "tools did not return, and never invent its data.\n\n"
    "DELIVERING CONTENT vs A RUN: When the user asks you to SEND a piece of "
    "content you produced (a summary, a comparison, an analysis, a note), use "
    "send_message and put that EXACT content in the body. send_artifact is ONLY "
    "for delivering a specific RUN's recommendation the user references (for "
    "example 'send the last run'). Do NOT call run_nba or send_artifact when the "
    "user just asked to send some text: that would send the wrong thing. Do NOT "
    "run a new NBA unless the user asks to run a decision.\n\n"
    "SENDING TO PEOPLE: Only send an email or Slack message when the user "
    "EXPLICITLY asks you to send it. Recipients may ONLY be (a) saved contacts, or "
    "(b) an exact address the user gave you. To send to a person, pass their NAME "
    "as the 'contact' argument to send_artifact (or the 'contacts' list for "
    "several); send_message likewise takes a contact NAME (or a user-given "
    "address) in its 'to' argument. Both resolve the name to the saved contact's "
    "REAL address, so pass the NAME, not a guessed address. NEVER "
    "invent or guess an email: do not build addresses like name@yourcompany.com, "
    "name@company.com, first.last@<accountname>.com, or any placeholder domain, and "
    "do not derive an address from a person's or account's name. If the name has no "
    "saved contact AND the user did not give an address, STOP and ASK the user for "
    "the address or to add the contact on the Contacts page: do NOT send. Only put "
    "an address in 'to' when the user gave that exact address verbatim. To email an "
    "account's people, pass the account and set all_account_contacts true. Report "
    "the exact recipients the tool returns, never a made-up one.\n\n"
    "RUNNING A DECISION: When the user asks to RUN something (for example 'run "
    "the nba', 'run a decision', 'run nba for <account>', 'increase ARR for X "
    "and email them'), you MUST call run_nba FIRST to execute the full planner "
    "and produce a FRESH recommendation. Do NOT reuse get_last_run or a prior "
    "run when asked to run a new decision. run_nba needs the account (id or "
    "name) and a short signal_text describing the situation/goal. Only AFTER "
    "run_nba returns do you deliver: chain send_artifact using that run's run_id. "
    "So 'run the nba for X and mail the contacts' is two tool calls in order: "
    "run_nba, then send_artifact.\n\n"
    "ACTING ON A PRIOR RUN: When the user explicitly refers to an EXISTING run "
    "(for example 'email the LAST run', 'send the previous recommendation'), use "
    "get_last_run / get_run to pull the stored recommendation, then chain "
    "send_artifact to deliver it, and tag_run to associate a run with an "
    "account or note. EMAIL always works: send_artifact with channel 'email' "
    "sends over the platform SES sender, no setup needed; pass 'to' for an "
    "explicit recipient address (for example 'email the latest run to "
    "someone@x.com'). SLACK needs the org's webhook connected in Settings: only "
    "if Slack is not configured, tell the user to connect it there. Do not "
    "claim email needs configuring.\n\n"
    "STRICT SCOPE: You ONLY assist with THIS platform: accounts and their "
    "signals, next best action decisions, domain packs, the knowledge base, "
    "policy guardrails, the learning loop, evaluation, and ingesting "
    "interactions. You are NOT a general assistant. If the user asks anything "
    "unrelated (writing code, math, trivia, world knowledge, general chit-chat, "
    "or any task the platform tools do not cover), politely DECLINE in one "
    "sentence and steer them back to what the platform can do. Do not answer "
    "off-topic questions even if you know the answer."
)


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------
def _event(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": kind, "data": data}


def _summarize_result(name: str, result: Any) -> str:
    """Build a short human summary of a tool result for the trace event."""

    if isinstance(result, dict):
        if "error" in result:
            return f"{name}: error - {result['error']}"
        if "sent" in result:
            if result["sent"]:
                return f"{name}: sent via {result.get('channel', 'channel')}"
            return f"{name}: not sent ({result.get('reason', 'unknown')})"
        if "tagged" in result:
            return f"{name}: tagged run {result.get('run_id', '')}"
        if "accounts" in result:
            return f"{name}: {result.get('count', 0)} accounts"
        if "domains" in result:
            keys = ", ".join(d.get("key", "") for d in result.get("domains", []))
            return f"{name}: {result.get('count', 0)} domains ({keys})"
        if "chunks" in result:
            return f"{name}: {result.get('count', 0)} chunks with citations"
        if "recommendation" in result and result.get("recommendation"):
            action = (result["recommendation"].get("action") or {}).get("title", "")
            return f"{name}: recommended '{action}'"
        if "artifact" in result:
            return f"{name}: generated {result.get('audit', {}).get('artifact_type', 'artifact')}"
        if "results" in result and "summary" in result:
            summ = result["summary"]
            return (
                f"{name}: {summ.get('passed', 0)} pass, {summ.get('warned', 0)} warn, "
                f"{summ.get('failed', 0)} fail"
            )
        if "accepted_rate" in result:
            return f"{name}: acceptance rate {result['accepted_rate']}"
        if "suites" in result:
            return f"{name}: {len(result.get('suites', []))} eval suites"
        if "chunks_written" in result:
            return f"{name}: wrote {result.get('chunks_written', 0)} chunks"
        if "profile" in result:
            return f"{name}: account {result['profile'].get('account_id', '')}"
        if "key" in result:
            return f"{name}: domain {result.get('key')}"
    return f"{name}: ok"


# ---------------------------------------------------------------------------
# ONLINE path: real LLM tool-calling
# ---------------------------------------------------------------------------
def _to_lc_messages(messages: List[Dict[str, str]]) -> List[Any]:
    """Convert wire messages into LangChain message objects."""

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    lc: List[Any] = [SystemMessage(content=_SYSTEM_PROMPT)]
    for msg in messages:
        role = (msg.get("role") or "user").lower()
        content = msg.get("content") or ""
        if role == "assistant":
            lc.append(AIMessage(content=content))
        elif role == "system":
            lc.append(SystemMessage(content=content))
        else:
            lc.append(HumanMessage(content=content))
    return lc


def _delta_text(chunk: Any) -> str:
    """Pull the incremental text from a streamed message chunk, if any."""

    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    # Some providers stream content as a list of parts; concatenate text parts.
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                out.append(part["text"])
        return "".join(out)
    return ""


def _reasoning_text(chunk: Any) -> str:
    """Best-effort extraction of a model's exposed reasoning/summary delta.

    Reasoning-capable models (and the OpenAI Responses API) surface their
    thinking outside ``content``: in ``additional_kwargs`` under keys like
    ``reasoning`` / ``reasoning_content``, sometimes as a string and sometimes as
    a ``{summary: [{text}]}`` structure. We read it defensively so a 'thinking'
    pulse can carry real summary text when available, and stay silent otherwise.
    """

    ak = getattr(chunk, "additional_kwargs", None)
    if not isinstance(ak, dict):
        return ""
    for key in ("reasoning_content", "reasoning"):
        val = ak.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict):
            summary = val.get("summary")
            if isinstance(summary, list):
                texts = [
                    s.get("text")
                    for s in summary
                    if isinstance(s, dict) and isinstance(s.get("text"), str)
                ]
                joined = "".join(t for t in texts if t)
                if joined.strip():
                    return joined
            text = val.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return ""


async def _stream_model(model: Any, convo: List[Any]):
    """Stream a model turn, yielding ('delta', text) for answer tokens and
    ('reasoning', text) for any exposed thinking, then ('done', message) with the
    fully accumulated message (carrying any tool calls) at the end."""

    gathered = None
    async for chunk in model.astream(convo):
        gathered = chunk if gathered is None else gathered + chunk
        reasoning = _reasoning_text(chunk)
        if reasoning:
            yield ("reasoning", reasoning)
        delta = _delta_text(chunk)
        if delta:
            yield ("delta", delta)
    yield ("done", gathered)


async def _stream_llm(
    messages: List[Dict[str, str]], context: Optional[Dict[str, Any]]
) -> AsyncIterator[Dict[str, Any]]:
    """Drive real OpenAI tool-calling, streaming tokens as the model produces them.

    Token deltas are emitted as ``message`` events the instant they arrive, tool
    calls stream as ``tool.called`` / ``tool.result`` as they happen, and the
    accumulated answer is sent once in a closing ``final`` frame.
    """

    from langchain_core.messages import ToolMessage

    from app.deps import get_llm

    llm = get_llm()
    bound = llm.bind_tools(toolkit.openai_tools())

    convo = _to_lc_messages(messages)
    trace: List[Dict[str, Any]] = []
    full_text = ""

    # Lightweight 'thinking' pulse the instant the turn starts, so the UI can show
    # a Thinking indicator before any token or tool call arrives.
    yield _event("thinking", {"text": "Analyzing your request"})

    for step in range(_MAX_STEPS):
        ai = None
        async for kind, payload in _stream_model(bound, convo):
            if kind == "delta":
                full_text += payload
                yield _event("message", {"content": payload})
            elif kind == "reasoning":
                # Surface the model's own reasoning/summary text when exposed.
                yield _event("thinking", {"text": payload})
            else:
                ai = payload
        if ai is None:
            break
        convo.append(ai)

        tool_calls = getattr(ai, "tool_calls", None) or []
        if not tool_calls:
            yield _event("final", {"content": full_text, "trace": trace})
            return

        # About to act: a thinking pulse between reasoning and tool execution.
        names = ", ".join(c.get("name") or "tool" for c in tool_calls)
        yield _event("thinking", {"text": f"Using {names}"})

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            yield _event("tool.called", {"tool": name, "args": args})
            result = await toolkit.run_tool(name, args)
            summary = _summarize_result(name, result)
            trace.append({"tool": name, "args": args, "summary": summary})
            yield _event("tool.result", {"tool": name, "summary": summary})
            convo.append(
                ToolMessage(
                    content=json.dumps(result, default=str),
                    tool_call_id=call.get("id") or name,
                )
            )

        # Tools done for this round: signal that we are reasoning over results.
        yield _event("thinking", {"text": "Reviewing results"})

    # Exhausted the step budget: stream a final summary with no further tools.
    async for kind, payload in _stream_model(llm, convo):
        if kind == "delta":
            full_text += payload
            yield _event("message", {"content": payload})
        elif kind == "reasoning":
            yield _event("thinking", {"text": payload})
    yield _event("final", {"content": full_text, "trace": trace})


# ---------------------------------------------------------------------------
# OFFLINE path: deterministic intent router
# ---------------------------------------------------------------------------
_ACCOUNT_RE = re.compile(r"\b(ACC-\d+)\b", re.IGNORECASE)
_DOMAIN_KEYS = ("customer_success", "saas_sales", "collections")


@functools.lru_cache(maxsize=1)
def _account_name_index() -> Dict[str, str]:
    """Map account names (and distinctive first words) to ids for the router.

    Lets the offline router resolve 'send the Northwind play to slack' to an
    account id. Best-effort: empty when the accounts slice is unavailable.
    """

    index: Dict[str, str] = {}
    try:
        from app.api.accounts import _accounts_by_id

        for aid, acc in _accounts_by_id().items():
            name = (acc.get("name") or "").lower().strip()
            if not name:
                continue
            index[name] = aid
            first = name.split()[0]
            if len(first) >= 5:
                index.setdefault(first, aid)
    except Exception:  # noqa: BLE001 - accounts slice optional
        return {}
    return index


def _detect_account_id(text: str) -> Optional[str]:
    """Resolve an account id from an explicit ACC-#### code or a known name."""

    match = _ACCOUNT_RE.search(text)
    if match:
        return match.group(1).upper()
    lowered = text.lower()
    for name, aid in _account_name_index().items():
        if name in lowered:
            return aid
    return None


def _detect_domain(text: str) -> Optional[str]:
    lowered = text.lower()
    for key in _DOMAIN_KEYS:
        if key in lowered or key.replace("_", " ") in lowered:
            return key
    if "sales" in lowered:
        return "saas_sales"
    if "collection" in lowered:
        return "collections"
    if "churn" in lowered or "customer success" in lowered:
        return "customer_success"
    return None


def _route(message: str, context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map a user message to an ordered list of {tool, args} calls.

    Ordered most-specific intent first so a single message lands on the right
    capability. Returns at least one call (a knowledge search) as a sensible
    default so the chat always does something useful.
    """

    text = message.strip()
    lowered = text.lower()
    ctx = context or {}
    account_id = _detect_account_id(text) or ctx.get("account_id")
    domain = _detect_domain(text) or ctx.get("domain")

    def has(*words: str) -> bool:
        return any(w in lowered for w in words)

    # Domains / verticals.
    if has("domain", "vertical", "pack") and has(
        "available", "list", "what", "which", "supported", "show", "have"
    ):
        return [{"tool": "list_domains", "args": {}}]

    # Learning loop.
    if has("learning", "acceptance", "accepted rate", "improving", "improve over"):
        return [{"tool": "get_learning", "args": {}}]

    # Evaluation.
    if has("eval", "evaluation", "quality score", "suite", "benchmark"):
        return [{"tool": "get_eval", "args": {}}]

    # Send a prior run's recommendation through a configured connector.
    # Checked before the NBA branch because 'recommendation' contains the
    # substring 'recommend'. Keyword route: a channel word
    # ('email'/'slack'/'gmail') with a run reference ('run'/'recommendation'/
    # 'play'/'last run'), or an explicit send verb plus a run reference.
    mentions_channel = has("email", "slack", "gmail")
    mentions_run = has("run", "recommendation", "last run", "play", "the rec")
    mentions_send = has("send", "fire off", "shoot over", "deliver", "forward")
    # 'email all contacts of <account>' / 'email everyone at ACC-1001' is also a
    # send: a plural/'everyone' contact reference triggers the fan-out.
    mentions_contacts = has("contact", "everyone")
    # An explicit request to RUN a new decision wins over send: 'run the nba and
    # mail them' must run_nba first, never deliver a stale prior run.
    wants_run = has("run the nba", "run nba", "run a decision", "run the decision") or (
        has("run") and has("nba", "decision", "next best action")
    )
    if not wants_run and (
        (mentions_channel and (mentions_run or mentions_send or mentions_contacts))
        or (mentions_send and (mentions_run or mentions_contacts))
    ):
        channel = "slack" if "slack" in lowered else ("gmail" if "gmail" in lowered else "email")
        send_args: Dict[str, Any] = {"channel": channel}
        run_id = ctx.get("run_id")
        if run_id:
            send_args["run_id"] = run_id
        if ctx.get("recommendation"):
            send_args["recommendation"] = ctx["recommendation"]
        if account_id:
            send_args["account_id"] = account_id
        # Fan out to every saved contact of the account when the user asks for
        # the account's contacts ('all contacts', 'every contact', 'everyone').
        if has("contacts", "everyone", "every contact", "all contacts"):
            send_args["all_account_contacts"] = True
        return [{"tool": "send_artifact", "args": send_args}]

    # Tag / associate a run with an account or note.
    if has("tag", "annotate", "associate", "label") and has("run"):
        tag_args: Dict[str, Any] = {}
        if ctx.get("run_id"):
            tag_args["run_id"] = ctx["run_id"]
        if account_id:
            tag_args["account_id"] = account_id
        tag_args["note"] = text
        return [{"tool": "tag_run", "args": tag_args}]

    # Run an NBA decision.
    if has(
        "next best action",
        "nba",
        "recommend",
        "what should",
        "what do we do",
        "play for",
        "run a decision",
        "decide",
    ):
        if account_id:
            args: Dict[str, Any] = {"account_id": account_id, "signal_text": text}
            if domain:
                args["domain"] = domain
            return [{"tool": "run_nba", "args": args}]
        # No account named: surface the inbox so the user can pick one.
        return [{"tool": "list_accounts", "args": ({"domain": domain} if domain else {})}]

    # Generate an artifact.
    if has("email", "draft", "slack", "crm task", "artifact", "generate", "write up"):
        artifact_type = "email"
        if "slack" in lowered:
            artifact_type = "slack"
        elif "crm" in lowered or "task" in lowered:
            artifact_type = "crm_task"
        args = {"artifact_type": artifact_type}
        run_id = ctx.get("run_id")
        if run_id:
            args["run_id"] = run_id
        if ctx.get("recommendation"):
            args["recommendation"] = ctx["recommendation"]
        if account_id:
            args["account_id"] = account_id
        return [{"tool": "execute_action", "args": args}]

    # Ingest an interaction.
    if has("ingest", "import", "log this", "save this note", "record this"):
        args = {"text": text}
        if account_id:
            args["account_id"] = account_id
        if domain:
            args["domain"] = domain
        return [{"tool": "ingest_interaction", "args": args}]

    # Policy check.
    if has("policy", "guardrail", "compliant", "allowed", "approval", "gate"):
        rec = ctx.get("recommendation") or {}
        args = {"recommendation": rec}
        if domain:
            args["domain"] = domain
        if account_id:
            args["account_id"] = account_id
        return [{"tool": "evaluate_policy", "args": args}]

    # Single account 360.
    if account_id and has("account", "show", "tell me about", "360", "detail", "status"):
        return [{"tool": "get_account", "args": {"account_id": account_id}}]

    # Account inbox / triage.
    if has(
        "account",
        "inbox",
        "triage",
        "riskiest",
        "at risk",
        "highest risk",
        "queue",
        "who needs",
    ):
        return [{"tool": "list_accounts", "args": ({"domain": domain} if domain else {})}]

    # Bare account id: show its 360.
    if account_id:
        return [{"tool": "get_account", "args": {"account_id": account_id}}]

    # Default: treat the message as a knowledge query.
    args = {"query": text}
    if domain:
        args["domain"] = domain
    return [{"tool": "search_knowledge", "args": args}]


def _compose_answer(calls: List[Dict[str, Any]], results: List[Any]) -> str:
    """Compose a clear textual answer from the executed tool results."""

    parts: List[str] = []
    for call, result in zip(calls, results):
        name = call["tool"]
        if not isinstance(result, dict):
            parts.append(str(result))
            continue
        if "error" in result:
            parts.append(f"I could not complete {name}: {result['error']}.")
            continue

        if name == "list_accounts":
            accounts = result.get("accounts", [])
            top = accounts[:5]
            lines = [
                f"- {a.get('name', a['account_id'])} ({a['account_id']}, {a.get('domain', '')}): "
                f"{a.get('risk_level', 'n/a')} risk, health {a.get('health_score', 'n/a')}"
                for a in top
            ]
            head = f"Top {len(top)} of {result.get('count', 0)} accounts by risk:"
            parts.append(head + "\n" + "\n".join(lines))

        elif name == "get_account":
            profile = result.get("profile", {})
            sigs = ", ".join(s.get("label", "") for s in result.get("signals", []))
            parts.append(
                f"{profile.get('name', profile.get('account_id', 'Account'))} "
                f"({profile.get('account_id', '')}): {profile.get('risk_level', 'n/a')} risk, "
                f"health {profile.get('health_score', 'n/a')}. Active signals: {sigs or 'none'}."
            )

        elif name == "list_domains":
            domains = result.get("domains", [])
            lines = [
                f"- {d.get('key')}: {d.get('actions_count', 0)} actions, "
                f"{d.get('decision_points_count', 0)} decision points"
                for d in domains
            ]
            parts.append(
                f"{result.get('count', 0)} domain packs are available:\n" + "\n".join(lines)
            )

        elif name == "get_domain":
            parts.append(
                f"Domain '{result.get('key')}': {result.get('description', '')}".strip()
            )

        elif name == "run_nba":
            rec = result.get("recommendation") or {}
            action = (rec.get("action") or {}).get("title", "no action")
            conf = (rec.get("confidence") or {}).get("score")
            rationale = rec.get("rationale", "")
            hitl = " Human approval is required." if result.get("requires_hitl") else ""
            parts.append(
                f"Next best action for {result.get('account_id')}: {action} "
                f"(confidence {conf}). {rationale}{hitl}".strip()
            )

        elif name == "search_knowledge":
            chunks = result.get("chunks", [])
            if not chunks:
                parts.append("No matching evidence was found in the knowledge base.")
            else:
                lines = [
                    f"- [{c['source_id']}] {c['snippet'][:160]}" for c in chunks[:4]
                ]
                parts.append(
                    f"Found {result.get('count', 0)} relevant snippets:\n" + "\n".join(lines)
                )

        elif name == "evaluate_policy":
            summary = result.get("summary", {})
            verdict = (
                "approval required" if result.get("requires_approval") else "cleared"
            )
            parts.append(
                f"Policy {verdict}: {summary.get('passed', 0)} pass, "
                f"{summary.get('warned', 0)} warn, {summary.get('failed', 0)} fail."
            )

        elif name == "execute_action":
            artifact = result.get("artifact", {})
            atype = result.get("audit", {}).get("artifact_type", "artifact")
            if atype == "email":
                parts.append(
                    f"Drafted email - subject: {artifact.get('subject', '')}\n\n"
                    f"{artifact.get('body', '')}"
                )
            elif atype == "slack":
                parts.append(f"Slack handoff:\n{artifact.get('message', '')}")
            else:
                parts.append(
                    f"CRM task - {artifact.get('title', '')}: {artifact.get('notes', '')}"
                )

        elif name == "ingest_interaction":
            parts.append(
                f"Ingested the interaction: wrote {result.get('chunks_written', 0)} "
                "retrievable chunks. It will ground the next decision."
            )

        elif name == "get_learning":
            parts.append(
                f"Learning loop: acceptance rate {result.get('accepted_rate', 0)} across "
                f"{result.get('decided', 0)} decided episodes "
                f"({result.get('approved', 0)} approved, {result.get('edited', 0)} edited, "
                f"{result.get('rejected', 0)} rejected)."
            )

        elif name == "get_eval":
            suites = result.get("suites", [])
            lines = [f"- {s['name']}: {s['metric']} {s['score']}" for s in suites]
            outcomes = result.get("outcomes", {})
            parts.append(
                "Evaluation suites:\n"
                + "\n".join(lines)
                + f"\nOutcome: {outcomes.get('kpi', '')} "
                f"{outcomes.get('baseline', '')} -> {outcomes.get('projected', '')} "
                f"{outcomes.get('unit', '')}"
            )

        elif name in ("get_last_run", "get_run"):
            if not result.get("recommendation"):
                parts.append(
                    result.get("message", "No matching run with a recommendation was found.")
                )
            else:
                action = result.get("action_title") or "a recommendation"
                parts.append(
                    f"Run {result.get('run_id')} for {result.get('account_id')}: "
                    f"{action} (status {result.get('status', 'n/a')})."
                )

        elif name == "send_artifact":
            channel = result.get("channel", "the channel")
            if result.get("sent"):
                target = result.get("to") or "Slack"
                parts.append(
                    f"Sent the recommendation to {target} via {channel} "
                    f"(run {result.get('run_id')})."
                )
            else:
                parts.append(
                    result.get("message")
                    or f"I could not send via {channel}: {result.get('reason', 'unknown')}."
                )

        elif name == "tag_run":
            tag = result.get("tagged", {})
            parts.append(
                f"Tagged run {result.get('run_id')} "
                f"(account {tag.get('account_id') or 'n/a'}, note: {tag.get('note') or 'none'})."
            )

        else:
            parts.append(json.dumps(result, default=str)[:400])

    return "\n\n".join(p for p in parts if p)


def _text_chunks(text: str, words_per_chunk: int = _WORDS_PER_CHUNK) -> List[str]:
    """Split text into whitespace-preserving word groups for progressive streaming.

    Each returned chunk keeps its trailing whitespace so concatenating the chunks
    reproduces the original answer exactly (the client appends deltas verbatim).
    """

    tokens = re.split(r"(\s+)", text)
    chunks: List[str] = []
    buf = ""
    words = 0
    for tok in tokens:
        if tok == "":
            continue
        buf += tok
        if tok.strip():
            words += 1
        if words >= words_per_chunk:
            chunks.append(buf)
            buf = ""
            words = 0
    if buf:
        chunks.append(buf)
    return chunks


async def _stream_offline(
    messages: List[Dict[str, str]], context: Optional[Dict[str, Any]]
) -> AsyncIterator[Dict[str, Any]]:
    """Deterministic router path: route, execute, compose, then stream the reply.

    Tool calls stream as they run (a ``tool.called`` then, after the tool resolves,
    a ``tool.result``) and the composed answer is chunked into ``message`` deltas
    so the streaming UX is visible with no key. The closing ``final`` carries the
    full answer and trace.
    """

    user_msg = ""
    for msg in reversed(messages):
        if (msg.get("role") or "user").lower() == "user":
            user_msg = msg.get("content") or ""
            break
    if not user_msg and messages:
        user_msg = messages[-1].get("content") or ""

    calls = _route(user_msg, context)
    results: List[Any] = []
    trace: List[Dict[str, Any]] = []

    # Offline still emits a sensible 'thinking' pulse so the UI's Thinking
    # indicator behaves the same with or without a key.
    yield _event("thinking", {"text": "Working through your request"})
    await asyncio.sleep(_CHUNK_DELAY)

    for call in calls:
        name = call["tool"]
        args = call.get("args") or {}
        # A pulse naming the capability about to run, between sequential tools.
        yield _event("thinking", {"text": f"Calling {name}"})
        yield _event("tool.called", {"tool": name, "args": args})
        # Brief pause so the "running" state is perceptible before the result.
        await asyncio.sleep(_TOOL_DELAY)
        result = await toolkit.run_tool(name, args)
        results.append(result)
        summary = _summarize_result(name, result)
        trace.append({"tool": name, "args": args, "summary": summary})
        yield _event("tool.result", {"tool": name, "summary": summary})

    yield _event("thinking", {"text": "Composing the answer"})
    answer = _compose_answer(calls, results) or "I am not sure how to help with that yet."
    for chunk in _text_chunks(answer):
        yield _event("message", {"content": chunk})
        await asyncio.sleep(_CHUNK_DELAY)
    yield _event("final", {"content": answer, "trace": trace})


# ---------------------------------------------------------------------------
# Public agent API
# ---------------------------------------------------------------------------
def _use_offline() -> bool:
    """True when the deterministic router should drive the chat."""

    from app.demo import demo_mode_enabled

    return demo_mode_enabled()


async def stream(
    messages: List[Dict[str, str]],
    context: Optional[Dict[str, Any]] = None,
    org_id: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream agent events for a conversation, picking the right path.

    Falls back to the deterministic router if the online path raises (e.g. a
    transient model error) so the chat never hard-fails mid-stream.
    """

    # Bind the caller's org for this turn so every org-scoped tool (retrieval,
    # runs, ingest, connectors) resolves to the authenticated tenant. The org
    # comes ONLY from the request's authenticated principal; we never derive the
    # tenant from client-supplied context (that would let a caller read another
    # org's data by spoofing it). set_current_org defaults to the demo org when
    # org_id is falsy (offline / no auth).
    toolkit.set_current_org(org_id)

    if _use_offline():
        async for event in _stream_offline(messages, context):
            yield event
        return

    tool_ran = False
    try:
        async for event in _stream_llm(messages, context):
            if "tool" in str(event.get("type", "")):
                tool_ran = True
            yield event
    except Exception:  # noqa: BLE001 - degrade to the deterministic path
        if tool_ran:
            # A tool already executed this turn (possibly side-effecting, e.g. an
            # email). Do NOT re-run the message through the offline router, which
            # could duplicate a send. Surface a soft error instead.
            yield {
                "type": "error",
                "data": {
                    "message": (
                        "I hit an error mid-task. Some steps may have completed, "
                        "please check before retrying."
                    )
                },
            }
        else:
            async for event in _stream_offline(messages, context):
                yield event


async def answer(
    messages: List[Dict[str, str]],
    context: Optional[Dict[str, Any]] = None,
    org_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the agent to completion and return the final answer plus tool trace."""

    final_content = ""
    trace: List[Dict[str, Any]] = []
    async for event in stream(messages, context, org_id=org_id):
        if event["type"] == "final":
            final_content = event["data"].get("content", "")
            trace = event["data"].get("trace", [])
    return {"answer": final_content, "trace": trace}
