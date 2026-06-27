"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Aperture, ArrowUp, Square } from "lucide-react";

import { ChatMessage } from "@/components/chat-message";
import { Press } from "@/components/ui/press";
import { cn } from "@/lib/utils";
import {
  sendChat,
  streamChat,
  type ChatStreamEvent,
} from "@/lib/api/chat";
import type { ChatMessage as ChatMessageType, ChatToolCall } from "@/lib/types";

// A turn extends the wire ChatMessage with the inline tool trace and a transient
// streaming flag the transcript renders. Only role + content are sent upstream.
export interface ChatTurn extends ChatMessageType {
  toolCalls?: ChatToolCall[];
  streaming?: boolean;
  // Optional reasoning text the stream may surface (rendered as "Thoughts").
  // Absent today; carried through so the UI lights up if a slice streams it.
  thoughts?: string;
}

const SUGGESTIONS = [
  "Run an NBA for Northwind and email the play to its contact",
  "Why did the planner skip the simulator on this run?",
  "Compare with-memory vs without-memory for ACC-1001",
  "Show the riskiest accounts, then open a run on the top one",
];

// Wire turns carry only the frozen-contract fields.
function toWire(turns: ChatTurn[]): ChatMessageType[] {
  return turns
    .filter((t) => t.content.trim().length > 0 || t.role === "user")
    .map((t) => ({ role: t.role, content: t.content }));
}

export interface ChatPanelProps {
  // The conversation to start from (a stored session's turns).
  initialTurns?: ChatTurn[];
  // Called with settled turns so the parent can persist this session.
  onTurnsChange?: (turns: ChatTurn[]) => void;
}

export function ChatPanel({ initialTurns, onTurnsChange }: ChatPanelProps) {
  const [turns, setTurns] = useState<ChatTurn[]>(initialTurns ?? []);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  // Lift turns up to the parent (which owns the session list + persistence) on
  // every change, including mid-stream, so the conversation is saved even if the
  // user navigates away before a turn settles. The parent debounces the actual
  // write, so this does not spam the API per token.
  useEffect(() => {
    onTurnsChange?.(turns);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turns]);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Keep the latest turn in view as tokens stream in.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Mutate the trailing assistant turn in place (token append, tool trace, etc).
  const updateAssistant = useCallback(
    (mut: (turn: ChatTurn) => ChatTurn) => {
      setTurns((prev) => {
        if (prev.length === 0) return prev;
        const next = prev.slice();
        const last = next[next.length - 1];
        if (last.role !== "assistant") return prev;
        next[next.length - 1] = mut(last);
        return next;
      });
    },
    [],
  );

  const applyEvent = useCallback(
    (evt: ChatStreamEvent) => {
      switch (evt.type) {
        case "token":
          updateAssistant((t) => ({ ...t, content: t.content + evt.content }));
          break;
        case "tool.called":
          updateAssistant((t) => ({
            ...t,
            toolCalls: [
              ...(t.toolCalls ?? []),
              { tool: evt.tool, args: evt.args },
            ],
          }));
          break;
        case "thinking":
          // Additive reasoning pulse: accumulate distinct lines into the turn's
          // "Thoughts" block. Defensive: ignore an empty or repeated pulse so the
          // block stays clean and an older event with no text is a no-op.
          updateAssistant((t) => {
            const line = (evt.text ?? "").trim();
            if (line.length === 0) return t;
            const prev = t.thoughts ?? "";
            if (prev === line || prev.endsWith(`\n${line}`)) return t;
            return { ...t, thoughts: prev ? `${prev}\n${line}` : line };
          });
          break;
        case "tool.result":
          updateAssistant((t) => {
            const calls = (t.toolCalls ?? []).slice();
            // Attach the summary to the most recent matching, unresolved call.
            for (let i = calls.length - 1; i >= 0; i -= 1) {
              if (calls[i].tool === evt.tool && !calls[i].summary) {
                calls[i] = { ...calls[i], summary: evt.summary };
                return { ...t, toolCalls: calls };
              }
            }
            calls.push({ tool: evt.tool, summary: evt.summary });
            return { ...t, toolCalls: calls };
          });
          break;
        case "final":
          updateAssistant((t) => ({
            ...t,
            content: evt.content && evt.content.length > 0 ? evt.content : t.content,
            toolCalls: evt.tool_calls ?? t.toolCalls,
          }));
          break;
        case "error":
          updateAssistant((t) => ({
            ...t,
            content:
              t.content.length > 0
                ? t.content
                : `Something went wrong: ${evt.message}`,
          }));
          break;
        default:
          break;
      }
    },
    [updateAssistant],
  );

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || busy) return;

      const history: ChatTurn[] = [
        ...turns,
        { role: "user", content: text },
      ];
      // Push the user turn plus an empty, streaming assistant placeholder.
      setTurns([
        ...history,
        { role: "assistant", content: "", toolCalls: [], streaming: true },
      ]);
      setInput("");
      setBusy(true);

      const controller = new AbortController();
      abortRef.current = controller;
      const wire = toWire(history);

      try {
        await streamChat(wire, applyEvent, controller.signal);
      } catch {
        if (controller.signal.aborted) {
          finalize();
          return;
        }
        // Streaming unavailable: try the non-streaming endpoint.
        try {
          const res = await sendChat(wire, controller.signal);
          applyEvent({
            type: "final",
            content: res.content,
            tool_calls: res.tool_calls,
          });
        } catch {
          if (!controller.signal.aborted) {
            await runOfflineFallback(text, applyEvent);
          }
        }
      } finally {
        finalize();
      }
    },
    [busy, turns, applyEvent],
  );

  const finalize = useCallback(() => {
    abortRef.current = null;
    setBusy(false);
    updateAssistant((t) => ({ ...t, streaming: false }));
  }, [updateAssistant]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };

  const empty = turns.length === 0;

  return (
    <div className="flex h-full flex-col">
      {/* Transcript */}
      <div
        ref={scrollRef}
        className="scroll-thin flex-1 overflow-y-auto px-4 py-6 md:px-6"
      >
        <div className="mx-auto w-full max-w-3xl">
          {empty ? (
            <EmptyState onPick={(s) => void send(s)} disabled={busy} />
          ) : (
            <div className="space-y-5">
              {turns.map((turn, i) => (
                <ChatMessage
                  key={i}
                  role={turn.role}
                  content={turn.content}
                  toolCalls={turn.toolCalls}
                  streaming={turn.streaming}
                  thoughts={turn.thoughts}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Composer */}
      <div className="border-t border-border bg-background/80 px-4 py-4 backdrop-blur md:px-6">
        <div className="mx-auto w-full max-w-3xl">
          {!empty && (
            <div className="mb-3 flex flex-wrap gap-2">
              {SUGGESTIONS.slice(0, 3).map((s) => (
                <Press
                  key={s}
                  onClick={() => void send(s)}
                  disabled={busy}
                  className="rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
                >
                  {s}
                </Press>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-1 focus-within:ring-offset-background">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              placeholder="Tell the agent what to do (run an NBA, email a contact, explain a run)..."
              className="max-h-40 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-relaxed text-foreground placeholder:text-muted-foreground focus-visible:outline-none"
            />
            {busy ? (
              <Press
                onClick={stop}
                aria-label="Stop generating"
                title="Stop"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-foreground hover:bg-secondary/80"
              >
                <Square className="h-3.5 w-3.5 fill-current" aria-hidden />
              </Press>
            ) : (
              <Press
                onClick={() => void send(input)}
                disabled={input.trim().length === 0}
                aria-label="Send message"
                title="Send"
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white transition-colors",
                  input.trim().length === 0
                    ? "bg-muted text-muted-foreground"
                    : "bg-primary hover:bg-[#C2613F]",
                )}
              >
                <ArrowUp className="h-4 w-4" aria-hidden />
              </Press>
            )}
          </div>
          <p className="mt-2 text-center text-[11px] text-muted-foreground">
            The agent invokes real platform tools, gated by human approval.
            Enter to send, Shift plus Enter for a new line.
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({
  onPick,
  disabled,
}: {
  onPick: (prompt: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col items-center pt-10 text-center md:pt-20">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-white shadow-sm ring-1 ring-primary/30">
        <Aperture className="h-6 w-6" aria-hidden />
      </div>
      <h2 className="mt-5 text-xl font-semibold tracking-tight">
        Operate the platform in plain language
      </h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        This is the agentic console, not a chatbot. It drives the same agents
        and tools the platform runs on: it can launch NBAs, tag runs, email a
        contact, query accounts, and explain planner decisions, calling each
        real tool live.
      </p>
      <div className="mt-8 w-full max-w-2xl text-left text-eyebrow">
        Try an agentic task
      </div>
      <div className="mt-2 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <Press
            key={s}
            onClick={() => onPick(s)}
            disabled={disabled}
            className="group flex items-start rounded-xl border border-border bg-card px-4 py-3 text-left text-sm text-foreground transition-colors hover:border-primary/40 hover:bg-secondary disabled:opacity-50"
          >
            <span className="line-clamp-2 text-muted-foreground group-hover:text-foreground">
              {s}
            </span>
          </Press>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Offline fallback
//
// When neither /chat/stream nor /chat is reachable, simulate a grounded reply
// so the surface stays alive for an offline demo. Deterministic, no network.
// ---------------------------------------------------------------------------

async function runOfflineFallback(
  prompt: string,
  emit: (evt: ChatStreamEvent) => void,
): Promise<void> {
  const plan = planOffline(prompt);

  for (const call of plan.tools) {
    emit({ type: "tool.called", tool: call.tool, args: call.args });
    await delay(260);
    emit({ type: "tool.result", tool: call.tool, summary: call.summary });
    await delay(120);
  }

  const words = plan.reply.split(" ");
  for (let i = 0; i < words.length; i += 1) {
    emit({ type: "token", content: (i === 0 ? "" : " ") + words[i] });
    await delay(18);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface OfflinePlan {
  tools: Required<ChatToolCall>[];
  reply: string;
}

function planOffline(prompt: string): OfflinePlan {
  const p = prompt.toLowerCase();

  if (p.includes("ingest") || p.includes("meeting note") || p.includes("note:")) {
    return {
      tools: [
        {
          tool: "ingest_text",
          args: { source_type: "meeting_notes" },
          summary: "Chunked and embedded 1 document into the retrieval corpus.",
        },
      ],
      reply:
        "I ingested that note as meeting_notes and indexed it for retrieval. It is now citeable evidence the engine can ground future recommendations on. Want me to run a next best action for the affected account?",
    };
  }

  if (p.includes("riskiest") || p.includes("at-risk") || p.includes("at risk") || p.includes("accounts")) {
    return {
      tools: [
        {
          tool: "list_accounts",
          args: { sort: "risk", limit: 3 },
          summary: "Returned 3 accounts ranked by churn risk.",
        },
      ],
      reply:
        "The riskiest accounts right now are Northwind Labs (health 38, 240k ARR, tickets up 40% MoM), Cobalt Retail Group (health 46, renewal in 45 days, no sponsor), and Helios Manufacturing (health 54, usage down 18%). Northwind is the most urgent given the high ARR and the skipped QBR. Want me to run a next best action for it?",
    };
  }

  if (p.includes("nba") || p.includes("next best") || p.includes("run an")) {
    return {
      tools: [
        {
          tool: "retrieve_evidence",
          args: { account_id: "acct_001" },
          summary: "Pulled 2 grounded signals: ticket spike and skipped QBR.",
        },
        {
          tool: "score_actions",
          args: { domain: "customer_success" },
          summary: "Ranked 9 candidate plays; top expected value 0.84.",
        },
        {
          tool: "create_run",
          args: { account_id: "acct_001" },
          summary: "Opened a run; recommendation pending human approval.",
        },
      ],
      reply:
        "For Northwind Labs I recommend scheduling an executive business review within 7 days (confidence 0.84, high). The drivers are a 40 percent month over month rise in support tickets and a skipped QBR, a classic pre-churn pattern for a high-ARR account. Without an executive touch before renewal, projected churn rises from 31 to roughly 58 percent. This is gated for your approval in the Inbox.",
    };
  }

  return {
    tools: [
      {
        tool: "describe_capabilities",
        args: {},
        summary: "Listed the platform's core tools and domains.",
      },
    ],
    reply:
      "This is an explainable next best action platform. I can ingest live customer interactions into a retrieval corpus, surface the riskiest accounts, and run the decision engine to produce evidence-backed, confidence-scored recommendations gated by human approval. Every action carries citations, alternatives with why-not reasons, and a counterfactual. Try asking me to show the riskiest accounts or run a next best action.",
  };
}

export default ChatPanel;
