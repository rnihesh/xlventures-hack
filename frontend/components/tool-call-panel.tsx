"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { AgentEvent } from "@/lib/useAgentStream";

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

export default ToolCallPanel;
