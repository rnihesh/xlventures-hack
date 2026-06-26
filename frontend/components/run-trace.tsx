"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { AgentEvent } from "@/lib/useAgentStream";

type StepStatus = "running" | "done" | "info" | "error";

interface TraceStep {
  key: string;
  label: string;
  detail?: string;
  status: StepStatus;
  ts: string;
  seq: number;
}

function readString(data: Record<string, unknown>, keys: string[]): string | undefined {
  for (const k of keys) {
    const v = data?.[k];
    if (typeof v === "string" && v.length > 0) return v;
  }
  return undefined;
}

// Fold the raw event log into an ordered, deduplicated timeline. Node lifecycle
// events collapse into a single step that flips from running to done.
function buildSteps(events: AgentEvent[]): TraceStep[] {
  const order: string[] = [];
  const byKey = new Map<string, TraceStep>();

  const upsert = (key: string, step: TraceStep) => {
    if (!byKey.has(key)) order.push(key);
    byKey.set(key, step);
  };

  for (const evt of events) {
    const data = evt.data || {};
    switch (evt.type) {
      case "run.started":
        upsert("run.started", {
          key: "run.started",
          label: "Run started",
          detail: readString(data, ["domain", "account_id"]),
          status: "info",
          ts: evt.ts,
          seq: evt.seq,
        });
        break;
      case "node.started": {
        const node = readString(data, ["node", "name", "label"]) || "node";
        const key = `node:${node}`;
        upsert(key, {
          key,
          label: node,
          detail: readString(data, ["capability", "description"]),
          status: "running",
          ts: evt.ts,
          seq: evt.seq,
        });
        break;
      }
      case "node.finished": {
        const node = readString(data, ["node", "name", "label"]) || "node";
        const key = `node:${node}`;
        const prev = byKey.get(key);
        upsert(key, {
          key,
          label: node,
          detail:
            readString(data, ["summary", "capability", "description"]) ??
            prev?.detail,
          status: "done",
          ts: evt.ts,
          seq: evt.seq,
        });
        break;
      }
      case "recommendation":
        upsert("recommendation", {
          key: "recommendation",
          label: "Recommendation emitted",
          status: "done",
          ts: evt.ts,
          seq: evt.seq,
        });
        break;
      case "hitl.required":
        upsert("hitl.required", {
          key: "hitl.required",
          label: "Human approval required",
          detail: readString(data, ["reason", "summary"]),
          status: "info",
          ts: evt.ts,
          seq: evt.seq,
        });
        break;
      case "run.finished":
        upsert("run.finished", {
          key: "run.finished",
          label: "Run finished",
          status: "done",
          ts: evt.ts,
          seq: evt.seq,
        });
        break;
      case "error":
        upsert(`error:${evt.seq}`, {
          key: `error:${evt.seq}`,
          label: "Error",
          detail: readString(data, ["message", "detail"]),
          status: "error",
          ts: evt.ts,
          seq: evt.seq,
        });
        break;
      default:
        break;
    }
  }

  return order
    .map((k) => byKey.get(k)!)
    .sort((a, b) => a.seq - b.seq);
}

const STATUS_STYLES: Record<StepStatus, { dot: string; badge: string; text: string }> = {
  running: {
    dot: "bg-amber-400 ring-amber-400/30 animate-pulse",
    badge: "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20",
    text: "Running",
  },
  done: {
    dot: "bg-emerald-500 ring-emerald-500/30",
    badge: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20",
    text: "Done",
  },
  info: {
    dot: "bg-sky-500 ring-sky-500/30",
    badge: "bg-sky-500/10 text-sky-600 dark:text-sky-400 ring-sky-500/20",
    text: "Info",
  },
  error: {
    dot: "bg-rose-500 ring-rose-500/30",
    badge: "bg-rose-500/10 text-rose-600 dark:text-rose-400 ring-rose-500/20",
    text: "Error",
  },
};

function fmtTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, {
    hour12: false,
    minute: "2-digit",
    second: "2-digit",
  });
}

export interface RunTraceProps {
  events: AgentEvent[];
  className?: string;
}

export function RunTrace({ events, className }: RunTraceProps) {
  const steps = buildSteps(events);

  return (
    <Card className={cn("h-full", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold tracking-tight">
            Planner trace
          </CardTitle>
          <span className="text-xs tabular-nums text-muted-foreground">
            {steps.length} step{steps.length === 1 ? "" : "s"}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {steps.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Waiting for the agent to start reasoning.
          </p>
        ) : (
          <ol className="relative ml-1 space-y-0">
            {steps.map((step, i) => {
              const style = STATUS_STYLES[step.status];
              const isLast = i === steps.length - 1;
              return (
                <li key={step.key} className="relative flex gap-3 pb-5">
                  {!isLast && (
                    <span
                      aria-hidden
                      className="absolute left-[5px] top-4 h-full w-px bg-border"
                    />
                  )}
                  <span
                    className={cn(
                      "relative z-10 mt-1 h-[11px] w-[11px] shrink-0 rounded-full ring-4",
                      style.dot,
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium capitalize text-foreground">
                        {step.label.replace(/_/g, " ")}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset",
                          style.badge,
                        )}
                      >
                        {style.text}
                      </span>
                    </div>
                    {step.detail && (
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {step.detail}
                      </p>
                    )}
                    <span className="mt-0.5 block text-[10px] tabular-nums text-muted-foreground/70">
                      {fmtTime(step.ts)}
                    </span>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

export default RunTrace;
