"use client";

import { cn } from "@/lib/utils";
import type { AgentEvent } from "@/lib/useAgentStream";

// ---------------------------------------------------------------------------
// Canonical topology. Mirrors backend app/graph/planner.py so the graph view
// can render the full planner -> specialists -> critic DAG even before (or
// without) live plan data. Selectable specialists are gated by the planner's
// roster; always-on nodes (gap analysis, critic, and the deterministic tail)
// always run.
// ---------------------------------------------------------------------------

type Phase = "plan" | "specialist" | "decision" | "commit";

interface NodeMeta {
  key: string;
  label: string;
  capability: string;
  phase: Phase;
  selectable?: boolean;
  alwaysOn?: boolean;
}

const TOPOLOGY: NodeMeta[] = [
  { key: "planner", label: "Planner", capability: "classify + route", phase: "plan", alwaysOn: true },
  { key: "retrieval", label: "Retrieval", capability: "evidence search", phase: "specialist", selectable: true },
  { key: "risk_scorer", label: "Risk Scorer", capability: "churn risk score", phase: "specialist", selectable: true },
  { key: "gap_analysis", label: "Gap Analysis", capability: "missing information", phase: "specialist", alwaysOn: true },
  { key: "play_recommender", label: "Play Recommender", capability: "rank plays", phase: "specialist", selectable: true },
  { key: "outcome_simulator", label: "Outcome Simulator", capability: "KPI projection", phase: "specialist", selectable: true },
  { key: "drafter", label: "Drafter", capability: "outreach draft", phase: "specialist", selectable: true },
  { key: "critic", label: "Critic", capability: "review + gate", phase: "decision", alwaysOn: true },
  { key: "policy_gate", label: "Policy Gate", capability: "business rules", phase: "commit", alwaysOn: true },
  { key: "hitl_gate", label: "Approval Gate", capability: "human in the loop", phase: "commit", alwaysOn: true },
  { key: "commit", label: "Commit", capability: "persist episode", phase: "commit", alwaysOn: true },
];

const PHASE_LABEL: Record<Phase, string> = {
  plan: "Plan",
  specialist: "Specialists",
  decision: "Decision",
  commit: "Commit",
};

const SELECTABLE = TOPOLOGY.filter((n) => n.selectable).map((n) => n.key);

// ---------------------------------------------------------------------------
// Typed reads over the loosely-typed SSE envelope.
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

type NodeStatus = "pending" | "running" | "done";

interface NodeRuntime {
  status: NodeStatus;
  latencyMs?: number;
  tool?: string;
  runs: number;
}

interface PlanInfo {
  roster: string[];
  skipped: string[];
  rationale?: string;
  decisionPoint?: string;
}

interface GraphModel {
  runtime: Map<string, NodeRuntime>;
  plan: PlanInfo | null;
  started: boolean;
  finished: boolean;
  active: boolean;
}

// Fold the raw SSE log into a per-node runtime plus the planner's dynamic plan.
function deriveGraph(events: AgentEvent[]): GraphModel {
  const runtime = new Map<string, NodeRuntime>();
  for (const meta of TOPOLOGY) {
    runtime.set(meta.key, { status: "pending", runs: 0 });
  }

  let plan: PlanInfo | null = null;
  let started = false;
  let finished = false;

  const ensure = (key: string): NodeRuntime => {
    let rt = runtime.get(key);
    if (!rt) {
      rt = { status: "pending", runs: 0 };
      runtime.set(key, rt);
    }
    return rt;
  };

  for (const evt of events) {
    const data = evt.data || {};
    switch (evt.type) {
      case "run.started":
        started = true;
        break;
      case "node.started": {
        const node = asString(data.node);
        if (!node) break;
        const rt = ensure(node);
        rt.status = "running";
        rt.runs += 1;
        break;
      }
      case "node.finished": {
        const node = asString(data.node);
        if (!node) break;
        const rt = ensure(node);
        rt.status = "done";
        const inner = asRecord(data.data);
        if (inner) {
          rt.latencyMs = asNumber(inner.latency_ms) ?? rt.latencyMs;
          rt.tool = asString(inner.tool) ?? rt.tool;
          // The planner carries the dynamic roster + rationale on its finish.
          // Prefer the first-class structured plan ({decision_point, roster,
          // skipped, rationale}); fall back to the routing block, then to the
          // raw capability list, so both new and older runs render.
          if (node === "planner") {
            const structured = asRecord(inner.plan);
            const routing = asRecord(inner.routing);
            const source = structured ?? routing;
            const roster =
              asStringArray(source?.roster).length > 0
                ? asStringArray(source?.roster)
                : asStringArray(inner.capabilities).filter((c) => c !== "critic");
            const explicitSkipped = asStringArray(source?.skipped);
            if (roster.length > 0 || source) {
              plan = {
                roster,
                skipped:
                  explicitSkipped.length > 0
                    ? explicitSkipped
                    : SELECTABLE.filter((k) => !roster.includes(k)),
                rationale:
                  asString(source?.rationale) ?? asString(inner.plan_rationale),
                decisionPoint:
                  asString(source?.decision_point) ?? asString(inner.decision_point),
              };
            }
          }
        }
        break;
      }
      case "run.finished":
        finished = true;
        break;
      default:
        break;
    }
  }

  // A finished run leaves nothing mid-flight: collapse any dangling running.
  if (finished) {
    for (const rt of runtime.values()) {
      if (rt.status === "running") rt.status = "done";
    }
  }

  const active = started && !finished;
  return { runtime, plan, started, finished, active };
}

// A node is inactive (greyed) when the planner explicitly skipped it, or, for
// older runs that carry no plan, when the run finished without ever entering it.
function isSkipped(meta: NodeMeta, model: GraphModel, rt: NodeRuntime): boolean {
  if (!meta.selectable) return false;
  if (model.plan) return model.plan.skipped.includes(meta.key);
  return model.finished && rt.runs === 0;
}

function fmtLatency(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`;
  return `${Math.round(ms)}ms`;
}

interface VisualStatus {
  status: NodeStatus | "skipped";
  dot: string;
  badge: string;
  label: string;
}

function visualFor(meta: NodeMeta, model: GraphModel, rt: NodeRuntime): VisualStatus {
  if (isSkipped(meta, model, rt)) {
    return {
      status: "skipped",
      dot: "border-2 border-dashed border-muted-foreground/40 bg-transparent",
      badge: "bg-muted/60 text-muted-foreground/70 ring-border",
      label: "Skipped",
    };
  }
  if (rt.status === "running") {
    return {
      status: "running",
      dot: "bg-primary ring-primary/30 animate-pulse shadow-[0_0_0_3px] shadow-primary/15",
      badge: "bg-primary/12 text-primary ring-primary/20",
      label: "Running",
    };
  }
  if (rt.status === "done") {
    return {
      status: "done",
      dot: "bg-primary/80 ring-primary/20",
      badge: "bg-primary/10 text-primary ring-primary/15",
      label: "Done",
    };
  }
  return {
    status: "pending",
    dot: "bg-muted-foreground/30 ring-border",
    badge: "bg-muted text-muted-foreground ring-border",
    label: model.active || model.started ? "Queued" : "Idle",
  };
}

export interface OrchestrationGraphProps {
  events: AgentEvent[];
  className?: string;
}

export function OrchestrationGraph({ events, className }: OrchestrationGraphProps) {
  // Degrade gracefully: nothing to draw until a run begins streaming.
  if (events.length === 0) return null;

  const model = deriveGraph(events);
  const ranCount = TOPOLOGY.filter((m) => (model.runtime.get(m.key)?.runs ?? 0) > 0).length;
  const skippedCount = TOPOLOGY.filter((m) => {
    const rt = model.runtime.get(m.key)!;
    return isSkipped(m, model, rt);
  }).length;

  return (
    <section
      className={cn(
        "rounded-xl border border-border bg-card/60 p-4",
        className,
      )}
    >
      <header className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              model.active ? "animate-pulse bg-primary" : "bg-muted-foreground/40",
            )}
          />
          <h3 className="text-sm font-semibold tracking-tight">
            Orchestration graph
          </h3>
        </div>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground tabular">
          {ranCount} ran{skippedCount > 0 ? ` / ${skippedCount} skipped` : ""}
        </span>
      </header>

      {/* The dynamic decision: which specialists the planner routed and why. */}
      {model.plan && (
        <div className="mb-4 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2.5">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-medium uppercase tracking-wide text-primary">
              Planner decision
            </span>
            {model.plan.decisionPoint && (
              <span className="truncate rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium capitalize text-primary ring-1 ring-inset ring-primary/20">
                {model.plan.decisionPoint.replace(/_/g, " ")}
              </span>
            )}
          </div>
          {model.plan.rationale && (
            <p className="mt-1 text-xs leading-relaxed text-foreground/80">
              {model.plan.rationale}
            </p>
          )}
          <p className="mt-1.5 text-[10px] text-muted-foreground">
            Routed {model.plan.roster.length} specialist
            {model.plan.roster.length === 1 ? "" : "s"}
            {model.plan.skipped.length > 0
              ? `, skipped ${model.plan.skipped.length}`
              : ""}
            .
          </p>
        </div>
      )}

      <ol className="relative ml-1 space-y-0">
        {TOPOLOGY.map((meta, i) => {
          const rt = model.runtime.get(meta.key)!;
          const vis = visualFor(meta, model, rt);
          const isLast = i === TOPOLOGY.length - 1;
          const prevPhase = i > 0 ? TOPOLOGY[i - 1].phase : null;
          const showPhase = meta.phase !== prevPhase;
          const muted = vis.status === "skipped" || vis.status === "pending";
          const tool = rt.tool && rt.tool !== meta.key ? rt.tool : meta.capability;

          return (
            <li key={meta.key}>
              {showPhase && (
                <p
                  className={cn(
                    "mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70",
                    i > 0 && "mt-2",
                  )}
                >
                  {PHASE_LABEL[meta.phase]}
                </p>
              )}
              <div className="relative flex animate-rise gap-3 pb-3.5">
                {!isLast && (
                  <span
                    aria-hidden
                    className={cn(
                      "absolute left-[5px] top-4 h-full w-px",
                      vis.status === "done" || vis.status === "running"
                        ? "bg-primary/30"
                        : "bg-border",
                    )}
                  />
                )}
                <span
                  className={cn(
                    "relative z-10 mt-1 h-[11px] w-[11px] shrink-0 rounded-full ring-4 ring-background",
                    vis.dot,
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={cn(
                        "flex min-w-0 items-center gap-1.5 text-sm font-medium",
                        muted ? "text-muted-foreground" : "text-foreground",
                      )}
                    >
                      <span className="truncate">{meta.label}</span>
                      {meta.alwaysOn && vis.status !== "skipped" && (
                        <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide text-muted-foreground ring-1 ring-inset ring-border">
                          always
                        </span>
                      )}
                      {rt.runs > 1 && (
                        <span
                          className="shrink-0 rounded bg-primary/10 px-1 py-0.5 text-[9px] font-medium text-primary ring-1 ring-inset ring-primary/20"
                          title={`Re-entered ${rt.runs} times (replan loop)`}
                        >
                          x{rt.runs}
                        </span>
                      )}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset",
                        vis.badge,
                      )}
                    >
                      {vis.label}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between gap-2">
                    <p
                      className={cn(
                        "truncate text-xs",
                        muted ? "text-muted-foreground/60" : "text-muted-foreground",
                      )}
                    >
                      {tool.replace(/_/g, " ")}
                    </p>
                    {rt.latencyMs !== undefined && vis.status === "done" && (
                      <span className="shrink-0 text-[10px] tabular text-muted-foreground/70">
                        {fmtLatency(rt.latencyMs)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default OrchestrationGraph;
