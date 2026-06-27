"use client";

import { useEffect, useState } from "react";
import {
  Wrench,
  Workflow,
  ArrowRight,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import {
  getAgents,
  getTools,
  type AgentCard,
  type ToolSpec,
} from "@/lib/api/agents";

// Cost tier and risk tier read as neutral-to-accent chips so the catalog stays
// grayscale with a single Claude-orange accent for the things that matter.
function costVariant(tier: string): "muted" | "secondary" | "warning" {
  if (tier === "strong") return "warning";
  if (tier === "cheap") return "muted";
  return "secondary";
}

function riskVariant(tier: string): "muted" | "secondary" | "danger" {
  if (tier === "high") return "danger";
  if (tier === "medium") return "secondary";
  return "muted";
}

function AgentCardView({ agent }: { agent: AgentCard }) {
  return (
    <div className="panel flex flex-col gap-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
            <Workflow className="h-[18px] w-[18px]" />
          </div>
          <div className="leading-tight">
            <div className="font-mono text-sm font-semibold tracking-tight">
              {agent.name || agent.capability}
            </div>
            <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              capability
            </div>
          </div>
        </div>
        <Badge variant={costVariant(agent.cost_tier)} className="capitalize">
          {agent.cost_tier}
        </Badge>
      </div>

      <p className="text-sm text-muted-foreground">{agent.description}</p>

      <div>
        <div className="mb-1.5 text-eyebrow">Produces state keys</div>
        <div className="flex flex-wrap gap-1.5">
          {agent.output_keys.length === 0 ? (
            <span className="text-xs text-muted-foreground">none</span>
          ) : (
            agent.output_keys.map((k) => (
              <code
                key={k}
                className="rounded-md border border-border bg-background/70 px-2 py-0.5 font-mono text-xs text-foreground"
              >
                {k}
              </code>
            ))
          )}
        </div>
      </div>

      {agent.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {agent.tags.map((t) => (
            <Badge key={t} variant="outline" className="capitalize">
              {t}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ToolsTable({ tools }: { tools: ToolSpec[] }) {
  return (
    <div className="panel overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-eyebrow">
              <th className="px-4 py-3 font-medium">Tool</th>
              <th className="px-4 py-3 font-medium">Description</th>
              <th className="px-4 py-3 font-medium">Effect</th>
              <th className="px-4 py-3 font-medium">Risk</th>
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => (
              <tr
                key={tool.name}
                className="border-b border-border last:border-0 align-top"
              >
                <td className="px-4 py-3">
                  <code className="font-mono text-xs font-semibold text-foreground">
                    {tool.name}
                  </code>
                  <div className="mt-0.5 text-[11px] uppercase tracking-[0.1em] text-muted-foreground">
                    {tool.kind}
                  </div>
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {tool.description}
                </td>
                <td className="px-4 py-3">
                  {tool.side_effecting ? (
                    <span className="inline-flex items-center gap-1.5 text-foreground">
                      <ShieldAlert className="h-4 w-4 text-primary" />
                      Side-effecting
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                      <ShieldCheck className="h-4 w-4" />
                      Read-only
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <Badge
                    variant={riskVariant(tool.risk_tier)}
                    className="capitalize"
                  >
                    {tool.risk_tier}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentCard[] | null>(null);
  const [tools, setTools] = useState<ToolSpec[] | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      const [a, t] = await Promise.all([
        getAgents(ctrl.signal),
        getTools(ctrl.signal),
      ]);
      setAgents(a);
      setTools(t);
    })();
    return () => ctrl.abort();
  }, []);

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-8">
      <PageHeader
        eyebrow="Platform"
        title="Agents and tools"
        description="The specialist registry the planner routes to at runtime, and the governance-tagged tools they can call."
      />

      <div>
        {/* Headline: the reusable, extensible agent + tool architecture. */}
        <div className="mb-8 flex flex-col gap-3 rounded-xl border border-primary/30 bg-primary/[0.04] p-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Workflow className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold tracking-tight">
                A reusable agent and tool framework.
              </h2>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Every specialist registers under a capability with the state
                keys it produces; the planner looks them up at runtime and never
                imports their code. Tools are tagged with governance metadata so
                the approval and risk story is auditable. Adding a capability is
                a registration, not a graph edit.
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2 rounded-md border border-border bg-background/70 px-3 py-1.5 font-mono text-xs text-muted-foreground">
            <span>signal</span>
            <ArrowRight className="h-3.5 w-3.5" />
            <span>planner</span>
            <ArrowRight className="h-3.5 w-3.5" />
            <span>capability</span>
          </div>
        </div>

        {/* Agents */}
        <section className="mb-10">
          <div className="mb-4 flex items-center gap-2">
            <Workflow className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold tracking-tight">
              Agent registry
            </h3>
            {agents && (
              <Badge variant="muted">{agents.length}</Badge>
            )}
          </div>

          {agents === null ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-56 rounded-lg" />
              ))}
            </div>
          ) : agents.length === 0 ? (
            <div className="panel">
              <EmptyState
                icon={Workflow}
                title="No agents registered"
                description="Register a specialist with @register_agent to add a capability to the planner."
              />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {agents.map((a) => (
                <AgentCardView key={a.capability} agent={a} />
              ))}
            </div>
          )}
        </section>

        {/* Tools */}
        <section>
          <div className="mb-4 flex items-center gap-2">
            <Wrench className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold tracking-tight">
              Tool registry
            </h3>
            {tools && <Badge variant="muted">{tools.length}</Badge>}
          </div>

          {tools === null ? (
            <Skeleton className="h-48 rounded-lg" />
          ) : tools.length === 0 ? (
            <div className="panel">
              <EmptyState
                icon={Wrench}
                title="No tools registered"
                description="Register a ToolSpec to expose a governance-tagged callable to the engine."
              />
            </div>
          ) : (
            <ToolsTable tools={tools} />
          )}
        </section>
      </div>
    </div>
  );
}
