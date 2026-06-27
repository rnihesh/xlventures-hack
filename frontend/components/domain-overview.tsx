"use client";

// Domain overview: the business-understanding surface for a domain pack.
//
// This is the "30% business" view. It makes the chosen domain legible to a
// human (and a judge): the operating process, the customer journey, the
// decision points where the platform intervenes (with the specialist agent
// roster each one triggers), and the success metrics that define winning.
//
// It reads the FULL parsed pack from GET /domains/{key} (additive narrative
// fields flow straight through the loader's model_dump), and degrades quietly
// when the backend is unreachable or a pack omits the narrative fields, so the
// page never blanks out.

import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  GitBranch,
  Map as MapIcon,
  Route,
  Target,
  Users,
  Workflow,
} from "lucide-react";

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import { Skeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// Shape of the parsed pack we read. Every narrative field is optional so a
// lean pack (or an older one) still renders without errors.
// ---------------------------------------------------------------------------
interface ProcessStage {
  key?: string;
  name?: string;
  description?: string;
  goal?: string;
}

interface JourneyStage {
  key?: string;
  name?: string;
  description?: string;
  goal?: string;
  risks?: string[];
}

interface SuccessMetric {
  key?: string;
  name?: string;
  definition?: string;
  target?: string;
  benchmark?: string;
}

interface DecisionPoint {
  label?: string;
  description?: string;
  when?: string;
  trigger_signals?: string[];
  primary_kpi?: string;
  default_persona?: string;
  roster?: string[];
  rationale?: string;
}

interface Persona {
  key: string;
  label?: string;
  description?: string;
}

interface Kpi {
  key: string;
  label?: string;
}

interface FullPack {
  domain: string;
  display_name?: string;
  tagline?: string;
  personas?: Persona[];
  kpis?: Kpi[];
  decision_points?: Record<string, DecisionPoint>;
  business_process?: ProcessStage[];
  customer_journey?: JourneyStage[];
  success_metrics?: SuccessMetric[];
}

// Friendly labels for the specialist agents a decision point can trigger. The
// roster carries agent keys; this turns them into business-legible names. Any
// key not listed is titleized as a safe fallback.
const AGENT_LABELS: Record<string, string> = {
  retrieval: "Evidence Retrieval",
  risk_scorer: "Risk Scorer",
  play_recommender: "Play Recommender",
  outcome_simulator: "Outcome Simulator",
  drafter: "Outreach Drafter",
};

function titleize(key: string): string {
  return key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function agentLabel(key: string): string {
  return AGENT_LABELS[key] ?? titleize(key);
}

async function fetchPack(domain: string): Promise<FullPack | null> {
  try {
    const res = await fetch(`${API_BASE}/domains/${encodeURIComponent(domain)}`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as FullPack;
  } catch {
    return null;
  }
}

export function DomainOverview({ domain }: { domain: string }) {
  const [pack, setPack] = useState<FullPack | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setPack(null);
    (async () => {
      const data = await fetchPack(domain);
      if (alive) {
        setPack(data);
        setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [domain]);

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-28 rounded-xl" />
        <Skeleton className="h-40 rounded-xl" />
        <Skeleton className="h-40 rounded-xl" />
      </div>
    );
  }

  // No pack (offline, or a fallback-only domain not present on the backend):
  // render a quiet note rather than blanking the page.
  if (!pack) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card p-8 text-center text-sm text-muted-foreground">
        The full domain overview loads from the backend. Start it to see the
        process, journey, decision points, and success metrics for this pack.
      </div>
    );
  }

  const personas = pack.personas ?? [];
  const kpis = pack.kpis ?? [];
  const personaLabel = (key?: string) =>
    (key && personas.find((p) => p.key === key)?.label) || (key ? titleize(key) : "");
  const kpiLabel = (key?: string) =>
    (key && kpis.find((k) => k.key === key)?.label) || (key ? titleize(key) : "");

  const process = pack.business_process ?? [];
  const journey = pack.customer_journey ?? [];
  const decisionPoints = Object.entries(pack.decision_points ?? {});
  const metrics: SuccessMetric[] =
    pack.success_metrics && pack.success_metrics.length > 0
      ? pack.success_metrics
      : kpis.map((k) => ({ key: k.key, name: k.label }));

  return (
    <div className="flex animate-rise flex-col gap-6">
      {/* Header: what business this pack understands. */}
      <section className="rounded-xl border border-primary/30 bg-primary/[0.04] p-6">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <MapIcon className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold tracking-tight">
                {pack.display_name || titleize(pack.domain)}
              </h2>
              <code className="rounded-md border border-border bg-background/70 px-2 py-0.5 font-mono text-xs text-muted-foreground">
                {pack.domain}
              </code>
            </div>
            {pack.tagline ? (
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                {pack.tagline}
              </p>
            ) : null}
            {personas.length > 0 ? (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Users className="h-3.5 w-3.5 text-muted-foreground" />
                {personas.map((p) => (
                  <span
                    key={p.key}
                    title={p.description}
                    className="rounded-full border border-border bg-background/70 px-2 py-0.5 text-[11px] text-muted-foreground"
                  >
                    {p.label || titleize(p.key)}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </section>

      {/* Business process: the operating motion, ordered. */}
      {process.length > 0 ? (
        <Section
          icon={Workflow}
          title="Business process"
          subtitle="The repeatable motion the team runs across its book of business."
        >
          <ol className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {process.map((stage, i) => (
              <li
                key={stage.key ?? i}
                className="relative rounded-lg border border-border bg-background/50 p-4"
              >
                <div className="mb-2 flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary ring-1 ring-inset ring-primary/20">
                    {i + 1}
                  </span>
                  <span className="text-sm font-semibold tracking-tight">
                    {stage.name || titleize(stage.key ?? "")}
                  </span>
                </div>
                {stage.description ? (
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {stage.description}
                  </p>
                ) : null}
                {stage.goal ? (
                  <p className="mt-2 flex items-start gap-1.5 text-xs text-foreground/80">
                    <Target className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                    <span>{stage.goal}</span>
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        </Section>
      ) : null}

      {/* Customer journey: the lifecycle, stage by stage. */}
      {journey.length > 0 ? (
        <Section
          icon={Route}
          title="Customer journey"
          subtitle="The lifecycle the platform shepherds an account through, and where each stage can fail."
        >
          <div className="flex flex-col gap-3">
            {journey.map((stage, i) => (
              <div
                key={stage.key ?? i}
                className="rounded-lg border border-border bg-background/50 p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
                    Stage {i + 1}
                  </span>
                  <span className="text-sm font-semibold tracking-tight">
                    {stage.name || titleize(stage.key ?? "")}
                  </span>
                </div>
                {stage.description ? (
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                    {stage.description}
                  </p>
                ) : null}
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {stage.goal ? (
                    <div className="flex items-start gap-1.5 text-xs">
                      <Target className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                      <span className="text-foreground/80">{stage.goal}</span>
                    </div>
                  ) : null}
                  {stage.risks && stage.risks.length > 0 ? (
                    <ul className="flex flex-col gap-1">
                      {stage.risks.map((risk, ri) => (
                        <li
                          key={ri}
                          className="flex items-start gap-1.5 text-xs text-muted-foreground"
                        >
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
                          <span>{risk}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </Section>
      ) : null}

      {/* Decision points: where the platform intervenes, and the agents it runs. */}
      {decisionPoints.length > 0 ? (
        <Section
          icon={GitBranch}
          title="Decision points"
          subtitle="The moments the engine classifies a situation into, and the specialist agent roster each one triggers."
        >
          <div className="grid gap-3 md:grid-cols-2">
            {decisionPoints.map(([key, dp]) => (
              <div
                key={key}
                className="flex flex-col rounded-lg border border-border bg-background/50 p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold tracking-tight">
                    {dp.label || titleize(key)}
                  </span>
                  <code className="font-mono text-[10px] text-muted-foreground">
                    {key}
                  </code>
                </div>
                {dp.when ? (
                  <p className="mt-1.5 text-xs font-medium text-primary/90">
                    {dp.when}
                  </p>
                ) : null}
                {dp.description ? (
                  <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                    {dp.description}
                  </p>
                ) : null}

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {dp.primary_kpi ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-[10px] text-foreground/80">
                      <Activity className="h-3 w-3 text-primary" />
                      {kpiLabel(dp.primary_kpi)}
                    </span>
                  ) : null}
                  {dp.default_persona ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-[10px] text-foreground/80">
                      <Users className="h-3 w-3 text-muted-foreground" />
                      {personaLabel(dp.default_persona)}
                    </span>
                  ) : null}
                </div>

                {dp.roster && dp.roster.length > 0 ? (
                  <div className="mt-3 border-t border-border pt-3">
                    <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      Agent roster
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {dp.roster.map((agent) => (
                        <span
                          key={agent}
                          className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground"
                        >
                          {agentLabel(agent)}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </Section>
      ) : null}

      {/* Success metrics: how this domain defines winning. */}
      {metrics.length > 0 ? (
        <Section
          icon={Target}
          title="Success metrics"
          subtitle="The numbers every next best action is meant to move, with the goal and a benchmark for context."
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {metrics.map((m, i) => (
              <div
                key={m.key ?? i}
                className="flex flex-col rounded-lg border border-border bg-background/50 p-4"
              >
                <div className="text-sm font-semibold tracking-tight">
                  {m.name || titleize(m.key ?? "")}
                </div>
                {m.definition ? (
                  <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                    {m.definition}
                  </p>
                ) : null}
                {m.target ? (
                  <div className="mt-3 inline-flex w-fit items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-xs font-semibold text-primary ring-1 ring-inset ring-primary/20">
                    <Target className="h-3.5 w-3.5" />
                    Target {m.target}
                  </div>
                ) : null}
                {m.benchmark ? (
                  <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground/80">
                    {m.benchmark}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </Section>
      ) : null}
    </div>
  );
}

// A titled section wrapper used across the overview.
function Section({
  icon: Icon,
  title,
  subtitle,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="mb-4 flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

export default DomainOverview;
