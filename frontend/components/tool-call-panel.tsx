"use client";

import { useMemo, useState } from "react";
import { Check, ChevronRight, Wrench } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { AgentEvent } from "@/lib/useAgentStream";
import type { ChatToolCall } from "@/lib/types";

// ---------------------------------------------------------------------------
// Event folding: pair node.started / node.finished into a tool invocation.
//
// The backend instrument helper nests the typed fields (tool, inputs_summary,
// outputs_summary, started, finished, latency_ms) inside the step's `data`,
// which the runs API forwards verbatim on node.finished. When those fields are
// absent we degrade gracefully: the tool name falls back to the node name and
// the latency is derived from the started/finished event timestamps.
// ---------------------------------------------------------------------------

type CallStatus = "running" | "done" | "error";

interface ToolCall {
  key: string;
  seq: number;
  node: string;
  tool: string;
  status: CallStatus;
  startedTs: string;
  finishedTs?: string;
  latencyMs?: number;
  inputsSummary?: string;
  outputsSummary?: string;
  raw?: Record<string, unknown>;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return undefined;
}

function readStr(
  source: Record<string, unknown> | undefined,
  key: string,
): string | undefined {
  const v = source?.[key];
  if (typeof v === "string" && v.length > 0) return v;
  return undefined;
}

function readNum(
  source: Record<string, unknown> | undefined,
  key: string,
): number | undefined {
  const v = source?.[key];
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return undefined;
}

function nodeName(data: Record<string, unknown>): string {
  return readStr(data, "node") || readStr(data, "name") || "node";
}

// Map each graph node to the underlying tool/function it invokes, so the Tool
// calls view reads as a function-call log (distinct from the narrative trace).
const NODE_TO_TOOL: Record<string, string> = {
  planner: "plan_strategy",
  retrieval: "search_knowledge",
  risk_scorer: "score_risk",
  play_recommender: "rank_plays",
  outcome_simulator: "simulate_outcome",
  drafter: "draft_artifact",
  critic: "verify_and_score",
  policy_gate: "evaluate_policy",
  hitl_gate: "request_approval",
  commit: "write_episode",
};

function toolForNode(node: string): string {
  return NODE_TO_TOOL[node] ?? node;
}

function buildCalls(events: AgentEvent[]): ToolCall[] {
  const calls: ToolCall[] = [];
  // Index of the most recent unfinished call per node, so a finish event
  // attaches to its matching start even when nodes interleave.
  const openByNode = new Map<string, number>();

  for (const evt of events) {
    const data = evt.data || {};
    if (evt.type === "node.started") {
      const node = nodeName(data);
      const idx = calls.length;
      calls.push({
        key: `call:${evt.seq}:${node}`,
        seq: evt.seq,
        node,
        tool: toolForNode(node),
        status: "running",
        startedTs: evt.ts,
      });
      openByNode.set(node, idx);
    } else if (evt.type === "node.finished") {
      const node = nodeName(data);
      const stepData = asRecord(data.data);
      const idx = openByNode.get(node);
      const target = idx !== undefined ? calls[idx] : undefined;

      const tool = readStr(stepData, "tool") || toolForNode(node);
      const inputsSummary = readStr(stepData, "inputs_summary");
      const outputsSummary =
        readStr(stepData, "outputs_summary") || readStr(data, "summary");
      const latencyMs = readNum(stepData, "latency_ms");

      if (target) {
        target.status = "done";
        target.finishedTs = evt.ts;
        target.tool = tool;
        target.inputsSummary = inputsSummary;
        target.outputsSummary = outputsSummary;
        target.latencyMs =
          latencyMs ?? deriveLatency(target.startedTs, evt.ts);
        target.raw = stepData;
        openByNode.delete(node);
      } else {
        // Finish without a matching start (e.g. replayed stream); synthesize.
        calls.push({
          key: `call:${evt.seq}:${node}`,
          seq: evt.seq,
          node,
          tool,
          status: "done",
          startedTs: evt.ts,
          finishedTs: evt.ts,
          latencyMs,
          inputsSummary,
          outputsSummary,
          raw: stepData,
        });
      }
    } else if (evt.type === "error") {
      // Mark the most recent running call (if any) as errored.
      for (let i = calls.length - 1; i >= 0; i -= 1) {
        if (calls[i].status === "running") {
          calls[i].status = "error";
          calls[i].finishedTs = evt.ts;
          calls[i].outputsSummary =
            readStr(data, "message") || readStr(data, "detail") || "error";
          break;
        }
      }
    }
  }

  return calls;
}

function deriveLatency(startedTs: string, finishedTs: string): number | undefined {
  const a = new Date(startedTs).getTime();
  const b = new Date(finishedTs).getTime();
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return undefined;
  return b - a;
}

function fmtLatency(ms?: number): string {
  if (ms === undefined) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

function latencyTone(ms?: number): "muted" | "danger" {
  if (ms === undefined) return "muted";
  if (ms < 1500) return "muted";
  return "danger";
}

function pretty(name: string): string {
  return name.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ToolCallRowProps {
  call: ToolCall;
  index: number;
}

function ToolCallRow({ call, index }: ToolCallRowProps) {
  const [open, setOpen] = useState(false);
  const dotTone =
    call.status === "running"
      ? "bg-primary animate-pulse"
      : call.status === "error"
        ? "bg-destructive"
        : "bg-foreground/50";

  return (
    <li className="animate-rise overflow-hidden rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-muted/50"
      >
        <span className="text-[10px] tabular text-muted-foreground/60">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className={cn("h-2 w-2 shrink-0 rounded-full", dotTone)} />
        <Wrench className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-[13px] font-medium text-foreground">
            {pretty(call.tool)}
          </span>
          {call.tool !== call.node && (
            <span className="block truncate text-[10px] text-muted-foreground">
              node: {pretty(call.node)}
            </span>
          )}
        </span>
        <Badge variant={latencyTone(call.latencyMs)} className="shrink-0 tabular">
          {call.status === "running" ? "running" : fmtLatency(call.latencyMs)}
        </Badge>
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
      </button>

      {open && (
        <div className="space-y-2.5 border-t border-border bg-muted/30 px-3 py-2.5 text-xs">
          <Field label="input" value={call.inputsSummary} mono />
          <Field
            label="output"
            value={call.outputsSummary}
            mono
            tone="accent"
          />
          {call.raw && Object.keys(call.raw).length > 0 && (
            <details className="group">
              <summary className="cursor-pointer select-none text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 hover:text-foreground">
                raw step data
              </summary>
              <pre className="mt-1.5 max-h-48 overflow-auto rounded-md bg-background p-2 text-[11px] leading-relaxed text-muted-foreground ring-1 ring-inset ring-border">
                {JSON.stringify(call.raw, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </li>
  );
}

function Field({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value?: string;
  mono?: boolean;
  tone?: "accent";
}) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
        {label}
      </div>
      <p
        className={cn(
          "mt-0.5 break-words text-foreground",
          mono && "font-mono text-[11px]",
          tone === "accent" && "text-primary",
          !value && "italic text-muted-foreground",
        )}
      >
        {value || "not reported"}
      </p>
    </div>
  );
}

export interface ToolCallPanelProps {
  events: AgentEvent[];
  className?: string;
}

export function ToolCallPanel({ events, className }: ToolCallPanelProps) {
  const calls = useMemo(() => buildCalls(events), [events]);

  const finished = calls.filter((c) => c.status === "done");
  const active = calls.some((c) => c.status === "running");
  const totalMs = finished.reduce((sum, c) => sum + (c.latencyMs ?? 0), 0);

  return (
    <Card className={cn("h-full", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold tracking-tight">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                active ? "animate-pulse bg-primary" : "bg-muted-foreground/40",
              )}
            />
            Tool calls
          </CardTitle>
          <div className="flex items-center gap-2 text-xs tabular text-muted-foreground">
            <span>
              {calls.length} call{calls.length === 1 ? "" : "s"}
            </span>
            {totalMs > 0 && (
              <>
                <span aria-hidden className="text-muted-foreground/40">
                  •
                </span>
                <span>{fmtLatency(totalMs)} total</span>
              </>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {calls.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No tool invocations yet. Run the agent to watch the orchestration.
          </p>
        ) : (
          <ol className="space-y-2">
            {calls.map((call, i) => (
              <ToolCallRow key={call.key} call={call} index={i} />
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

// ===========================================================================
// Chat tool timeline
//
// The copilot chat surfaces the tools the agent calls inline in an assistant
// turn. This renders that sequence as a single connected vertical thread (a
// thin rail links each tool's status dot to the next), where each card is
// clickable to reveal the exact INPUT (args) and OUTPUT (result) it ran with.
//
// Reads ChatToolCall defensively: `args` is the tool input, `summary` is the
// result. A call with no `summary` while the turn is still streaming is treated
// as in flight (animated). Once the turn settles, the whole group collapses to
// a compact "Used N tools" row the user can re-expand.
// ===========================================================================

function isJsonLike(value: string): boolean {
  const t = value.trim();
  return (
    (t.startsWith("{") && t.endsWith("}")) ||
    (t.startsWith("[") && t.endsWith("]"))
  );
}

// Pretty print a result string: parse-and-reformat when it looks like JSON,
// otherwise return it as-is so plain summaries stay readable.
function prettyResult(value: string): string {
  if (isJsonLike(value)) {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return value;
}

// Flatten args into readable key/value rows. Object/array values are
// pretty-printed JSON; scalars render inline.
function argRows(
  args?: Record<string, unknown>,
): { key: string; value: string }[] {
  if (!args) return [];
  return Object.entries(args).map(([key, v]) => ({
    key,
    value:
      typeof v === "string"
        ? v
        : typeof v === "number" || typeof v === "boolean" || v === null
          ? String(v)
          : JSON.stringify(v, null, 2),
  }));
}

// Collapsed one-line preview of what a tool did (or is doing).
function chatSummaryLine(call: ChatToolCall, running: boolean): string {
  if (call.summary && call.summary.trim().length > 0) return call.summary;
  if (running) return "Working...";
  const rows = argRows(call.args).slice(0, 3);
  if (rows.length > 0) {
    return rows
      .map((r) => `${r.key}: ${r.value.replace(/\s+/g, " ").slice(0, 40)}`)
      .join(", ");
  }
  return "No result reported";
}

// Three small dots that pulse in sequence: the universal "working" cue.
function RunningDots({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
    </span>
  );
}

interface ChatToolCardProps {
  call: ChatToolCall;
  index: number;
  running: boolean;
  isLast: boolean;
}

function ChatToolCard({ call, index, running, isLast }: ChatToolCardProps) {
  const [open, setOpen] = useState(false);
  const rows = argRows(call.args);
  const hasInput = rows.length > 0;
  const hasOutput = !!call.summary && call.summary.trim().length > 0;

  return (
    <li className="relative flex gap-3">
      {/* Connector rail: a status dot sitting on a thin vertical line that
          links this card to the next, so the calls read as one linked flow. */}
      <div className="relative flex w-4 shrink-0 flex-col items-center">
        <span className="relative mt-3 flex h-2.5 w-2.5 items-center justify-center">
          {running && (
            <span className="absolute inset-0 animate-ping rounded-full bg-primary/40" />
          )}
          <span
            className={cn(
              "relative h-2.5 w-2.5 rounded-full ring-2 ring-card",
              running ? "bg-primary" : "bg-primary/70",
            )}
          />
        </span>
        {!isLast && <span className="w-px flex-1 bg-border" />}
      </div>

      <div className={cn("min-w-0 flex-1", isLast ? "pb-0" : "pb-2")}>
        <div className="overflow-hidden rounded-lg border border-border bg-card/70">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex w-full items-center gap-2.5 px-2.5 py-2 text-left transition-colors hover:bg-muted/40"
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Wrench className="h-3.5 w-3.5" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5">
                <span className="truncate font-mono text-[12px] font-semibold text-foreground">
                  {call.tool}
                </span>
                <span className="text-[10px] tabular text-muted-foreground/50">
                  {String(index + 1).padStart(2, "0")}
                </span>
              </span>
              <span className="mt-0.5 block truncate text-[11px] leading-snug text-muted-foreground">
                {chatSummaryLine(call, running)}
              </span>
            </span>
            <span
              className={cn(
                "flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                running
                  ? "bg-primary/10 text-primary"
                  : "bg-secondary text-muted-foreground",
              )}
            >
              {running ? (
                <>
                  <RunningDots />
                  <span>Running</span>
                </>
              ) : (
                <>
                  <Check className="h-3 w-3 text-primary" aria-hidden />
                  <span>Done</span>
                </>
              )}
            </span>
            <ChevronRight
              className={cn(
                "h-4 w-4 shrink-0 text-muted-foreground/70 transition-transform",
                open && "rotate-90",
              )}
              aria-hidden
            />
          </button>

          {open && (
            <div className="space-y-2.5 border-t border-border bg-muted/30 px-2.5 py-2.5">
              <div>
                <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                  Input
                </div>
                {hasInput ? (
                  <dl className="mt-1 space-y-1">
                    {rows.map((r) => (
                      <div
                        key={r.key}
                        className="grid grid-cols-[minmax(0,7rem)_1fr] gap-2"
                      >
                        <dt className="truncate font-mono text-[11px] text-muted-foreground">
                          {r.key}
                        </dt>
                        <dd className="min-w-0">
                          {r.value.includes("\n") ? (
                            <pre className="overflow-auto rounded bg-background p-1.5 font-mono text-[11px] leading-relaxed text-foreground ring-1 ring-inset ring-border">
                              {r.value}
                            </pre>
                          ) : (
                            <span className="break-words font-mono text-[11px] text-foreground">
                              {r.value}
                            </span>
                          )}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="mt-1 text-[11px] italic text-muted-foreground">
                    No arguments
                  </p>
                )}
              </div>

              <div>
                <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                  Output
                </div>
                {hasOutput ? (
                  isJsonLike(call.summary!) ? (
                    <pre className="mt-1 max-h-56 overflow-auto rounded bg-background p-1.5 font-mono text-[11px] leading-relaxed text-foreground ring-1 ring-inset ring-border">
                      {prettyResult(call.summary!)}
                    </pre>
                  ) : (
                    <p className="mt-1 break-words text-[11px] leading-relaxed text-primary">
                      {call.summary}
                    </p>
                  )
                ) : running ? (
                  <p className="mt-1 inline-flex items-center gap-1.5 text-[11px] italic text-muted-foreground">
                    <RunningDots />
                    waiting for result
                  </p>
                ) : (
                  <p className="mt-1 text-[11px] italic text-muted-foreground">
                    No result reported
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

export interface ChatToolTimelineProps {
  calls: ChatToolCall[];
  // True while the assistant turn is still streaming. A call with no result
  // during streaming is in flight; once the turn settles all calls read as done.
  streaming: boolean;
  className?: string;
}

export function ChatToolTimeline({
  calls,
  streaming,
  className,
}: ChatToolTimelineProps) {
  // When the turn has settled, default to a collapsed summary row; the user can
  // click to re-open the full thread. While streaming we always show the thread.
  const [open, setOpen] = useState(false);

  if (calls.length === 0) return null;

  const runningIndex = streaming
    ? calls.findIndex((c) => c.summary === undefined)
    : -1;
  const groupComplete = !streaming;
  const expanded = !groupComplete || open;

  const thread = (
    <ol className="relative">
      {calls.map((call, i) => (
        <ChatToolCard
          key={`${call.tool}-${i}`}
          call={call}
          index={i}
          running={streaming && i === runningIndex}
          isLast={i === calls.length - 1}
        />
      ))}
    </ol>
  );

  if (!groupComplete) {
    return <div className={className}>{thread}</div>;
  }

  // Settled: compact summary row that toggles the full thread.
  return (
    <div className={cn("rounded-lg", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-lg border border-border bg-card/70 px-2.5 py-1.5 text-left transition-colors hover:bg-muted/40"
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Wrench className="h-3 w-3" aria-hidden />
        </span>
        <span className="flex-1 text-[12px] font-medium text-foreground">
          Used {calls.length} tool{calls.length === 1 ? "" : "s"}
        </span>
        <span className="text-[11px] text-muted-foreground">
          {expanded ? "Hide" : "Show"}
        </span>
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground/70 transition-transform",
            expanded && "rotate-90",
          )}
          aria-hidden
        />
      </button>
      {expanded && <div className="mt-2">{thread}</div>}
    </div>
  );
}

export default ToolCallPanel;
