// Typed client for the generic chat surface.
//
// The chat lets a user ask the platform to do anything and watch the tools the
// agent calls along the way. streamChat POSTs the transcript to /chat/stream
// and parses the SSE envelope (message tokens, tool.called, tool.result, and a
// final frame) into normalized events. sendChat is a non-streaming fallback to
// /chat for environments where streaming is unavailable.
//
// Both carry Authorization via authHeaders. Field names are read permissively
// so the UI keeps working across small backend shape differences.

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import type { ChatMessage, ChatToolCall } from "@/lib/types";

// Normalized stream event the UI consumes. The transport may deliver these as a
// flat object ({ type, content }) or an AgentEvent-style envelope
// ({ type, data: { ... } }); normalize() collapses both into this shape.
export type ChatStreamEvent =
  | { type: "token"; content: string }
  | { type: "tool.called"; tool: string; args?: Record<string, unknown> }
  | { type: "tool.result"; tool: string; summary?: string }
  | { type: "thinking"; text?: string }
  | { type: "final"; content?: string; tool_calls?: ChatToolCall[] }
  | { type: "error"; message: string };

export interface ChatResponse {
  content: string;
  tool_calls?: ChatToolCall[];
}

// ---------------------------------------------------------------------------
// SSE frame parsing (mirrors the run stream reader).
// ---------------------------------------------------------------------------

// Split a raw chunk buffer into complete "data: ...\n\n" frames. Returns the
// decoded JSON payloads found and the leftover (incomplete) buffer tail.
function drainFrames(buffer: string): { events: unknown[]; rest: string } {
  const events: unknown[] = [];
  // sse-starlette frames events with CRLF (\r\n\r\n). Normalize to LF so the
  // \n\n frame split below matches; otherwise no frame is ever parsed.
  let rest = buffer.replace(/\r\n/g, "\n");
  let sep = rest.indexOf("\n\n");
  while (sep !== -1) {
    const rawFrame = rest.slice(0, sep);
    rest = rest.slice(sep + 2);
    const dataLines = rawFrame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""));
    if (dataLines.length > 0) {
      const payload = dataLines.join("\n").trim();
      if (payload.length > 0) {
        try {
          events.push(JSON.parse(payload));
        } catch {
          // Ignore a malformed frame and keep streaming.
        }
      }
    }
    sep = rest.indexOf("\n\n");
  }
  return { events, rest };
}

function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function asRecord(v: unknown): Record<string, unknown> | undefined {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : undefined;
}

// Read the first present key from the frame, checking both the top level and a
// nested `data` envelope.
function pick(
  top: Record<string, unknown>,
  data: Record<string, unknown>,
  keys: string[],
): unknown {
  for (const k of keys) {
    if (top[k] !== undefined) return top[k];
    if (data[k] !== undefined) return data[k];
  }
  return undefined;
}

function readToolCalls(value: unknown): ChatToolCall[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const calls: ChatToolCall[] = [];
  for (const entry of value) {
    const rec = asRecord(entry);
    if (!rec) continue;
    const tool =
      asString(rec.tool) ?? asString(rec.name) ?? asString(rec.function);
    if (!tool) continue;
    calls.push({
      tool,
      args: asRecord(rec.args ?? rec.arguments ?? rec.input),
      summary: asString(rec.summary ?? rec.result ?? rec.output),
    });
  }
  return calls.length ? calls : undefined;
}

// Map a raw SSE payload onto a normalized ChatStreamEvent.
function normalize(raw: unknown): ChatStreamEvent | null {
  const top = asRecord(raw);
  if (!top) return null;
  const data = asRecord(top.data) ?? top;
  const type = (asString(top.type) ?? asString(data.type) ?? "token").toLowerCase();

  switch (type) {
    case "token":
    case "message":
    case "delta":
    case "message.delta": {
      const content =
        asString(pick(top, data, ["content", "token", "delta", "text"])) ?? "";
      return { type: "token", content };
    }
    case "tool.called":
    case "tool_call":
    case "tool.call":
    case "tool_called": {
      const tool = asString(pick(top, data, ["tool", "name", "function"]));
      if (!tool) return null;
      return {
        type: "tool.called",
        tool,
        args: asRecord(pick(top, data, ["args", "arguments", "input"])),
      };
    }
    case "tool.result":
    case "tool_result":
    case "tool.output": {
      const tool = asString(pick(top, data, ["tool", "name", "function"])) ?? "tool";
      return {
        type: "tool.result",
        tool,
        summary: asString(
          pick(top, data, ["summary", "result", "output", "content"]),
        ),
      };
    }
    case "thinking":
    case "reasoning": {
      // Additive event: a reasoning / status pulse the agent may emit before or
      // between tool calls. Read the text permissively; it is optional so an
      // older or empty event never breaks the stream.
      return {
        type: "thinking",
        text: asString(pick(top, data, ["text", "content", "summary"])),
      };
    }
    case "final":
    case "done":
    case "complete":
    case "message.final": {
      return {
        type: "final",
        content: asString(pick(top, data, ["content", "message", "text", "answer"])),
        tool_calls: readToolCalls(pick(top, data, ["tool_calls", "tools", "trace"])),
      };
    }
    case "error": {
      return {
        type: "error",
        message:
          asString(pick(top, data, ["message", "detail", "error"])) ??
          "Chat error",
      };
    }
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Stream a chat completion. POSTs the transcript to /chat/stream and invokes
 * onEvent for each normalized envelope frame. Throws if the request fails or
 * streaming is unavailable so the caller can fall back to sendChat.
 */
export async function streamChat(
  messages: ChatMessage[],
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: authHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }),
    credentials: "include",
    body: JSON.stringify({ messages }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`Chat stream failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = drainFrames(buffer);
    buffer = rest;
    for (const raw of events) {
      const evt = normalize(raw);
      if (evt) onEvent(evt);
    }
  }
  // Flush any trailing frame.
  buffer += decoder.decode();
  const { events } = drainFrames(buffer + "\n\n");
  for (const raw of events) {
    const evt = normalize(raw);
    if (evt) onEvent(evt);
  }
}

/**
 * Non-streaming fallback. POSTs the transcript to /chat and returns the full
 * assistant reply plus any tool calls. Throws on failure.
 */
export async function sendChat(
  messages: ChatMessage[],
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ messages }),
    signal,
  });
  if (!res.ok) {
    throw new Error(`Chat failed (${res.status})`);
  }
  const body = (await res.json()) as Record<string, unknown>;
  const data = asRecord(body.data) ?? body;
  const content =
    asString(data.answer) ??
    asString(data.content) ??
    asString(data.message) ??
    asString(data.reply) ??
    asString(data.text) ??
    "";
  return {
    content,
    tool_calls: readToolCalls(data.trace ?? data.tool_calls ?? data.tools),
  };
}
