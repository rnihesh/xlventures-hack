"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Building2,
  CheckCircle2,
  Inbox,
  Play,
  TrendingUp,
  Boxes,
  GraduationCap,
  FlaskConical,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { riskVariant, formatArr } from "@/components/account-table";
import { cn } from "@/lib/utils";
import { getAccounts, getEval, getLearning } from "@/lib/api";
import type { Account, EvalReport, Learning } from "@/lib/types";

interface Kpi {
  label: string;
  value: string;
  sub: string;
  icon: LucideIcon;
  tone: string;
  // When set, the value is a labeled projection (not an actual); the string is
  // the method shown on hover.
  projected?: string;
}

const QUICK_LINKS: {
  href: string;
  label: string;
  desc: string;
  icon: LucideIcon;
}[] = [
  {
    href: "/inbox",
    label: "Triage inbox",
    desc: "Work the prioritized queue of at-risk accounts.",
    icon: Inbox,
  },
  {
    href: "/run",
    label: "Run an agent",
    desc: "Turn a raw signal into an explainable action.",
    icon: Play,
  },
  {
    href: "/learning",
    label: "Learning loop",
    desc: "See how outcomes reshape recommendations.",
    icon: GraduationCap,
  },
  {
    href: "/eval",
    label: "Evaluation",
    desc: "Faithfulness, calibration, and guardrails.",
    icon: FlaskConical,
  },
  {
    href: "/domains",
    label: "Domain packs",
    desc: "Swap the use case without touching the engine.",
    icon: Boxes,
  },
];

function KpiCard({ kpi }: { kpi: Kpi }) {
  const Icon = kpi.icon;
  return (
    <div className="panel animate-rise p-5">
      <div className="flex items-center justify-between">
        <span className="text-eyebrow">{kpi.label}</span>
        <span
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-lg",
            kpi.tone,
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className="font-mono text-3xl font-semibold tracking-tight tabular">
          {kpi.value}
        </span>
        {kpi.projected ? (
          <span
            className="cursor-help rounded-full bg-secondary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground"
            title={kpi.projected}
          >
            Projected
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{kpi.sub}</p>
    </div>
  );
}

export default function OverviewPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [learning, setLearning] = useState<Learning | null>(null);
  const [evalReport, setEvalReport] = useState<EvalReport | null>(null);
  const [error, setError] = useState(false);
  const [nonce, setNonce] = useState(0);

  const retry = useCallback(() => {
    setError(false);
    setAccounts(null);
    setLearning(null);
    setEvalReport(null);
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void Promise.all([
      getAccounts(ctrl.signal),
      getLearning(ctrl.signal),
      getEval(ctrl.signal),
    ])
      .then(([a, l, e]) => {
        setAccounts(a);
        setLearning(l);
        setEvalReport(e);
      })
      .catch((err) => {
        if (err?.name !== "AbortError") setError(true);
      });
    return () => ctrl.abort();
  }, [nonce]);

  const atRisk = accounts?.filter((a) => {
    const r = String(a.risk_level).toLowerCase();
    return r === "high" || r === "critical";
  });
  const arrAtRisk = atRisk?.reduce((sum, a) => sum + a.arr, 0) ?? 0;
  const recentRisk = [...(accounts ?? [])]
    .sort((a, b) => a.health_score - b.health_score)
    .slice(0, 5);

  // Honest empty states: acceptance and NRR only show real numbers once the
  // learning loop has recorded outcomes. No fabricated baseline.
  const decidedCount =
    learning?.decided ??
    learning?.episodes.filter((e) => {
      const d = String(e.decision ?? "").toLowerCase();
      return d.includes("approve") || d.includes("reject") || d.includes("edit");
    }).length ??
    0;
  const hasRuns = decidedCount > 0;
  const nrrHasData = !!learning?.before_after.has_data;
  const evalUplift = evalReport
    ? Number(evalReport.outcomes.projected) - Number(evalReport.outcomes.baseline)
    : null;

  const kpis: Kpi[] = [
    {
      label: "Accounts at risk",
      value: atRisk ? String(atRisk.length) : "--",
      sub: `${formatArr(arrAtRisk)} ARR exposed`,
      icon: AlertTriangle,
      tone: "bg-destructive/10 text-destructive",
    },
    {
      label: "Acceptance rate",
      value:
        learning && hasRuns
          ? `${Math.round(learning.accepted_rate * 100)}%`
          : "--",
      sub: hasRuns
        ? `Across ${decidedCount} recorded ${decidedCount === 1 ? "decision" : "decisions"}`
        : "No runs yet",
      icon: CheckCircle2,
      tone: "bg-primary/10 text-primary",
    },
    {
      label: "NRR projected",
      value:
        learning && nrrHasData ? `${learning.before_after.after}%` : "--",
      sub:
        learning && nrrHasData
          ? `From ${learning.before_after.before}% on early decisions`
          : "Learning loop warming up",
      icon: TrendingUp,
      tone: "bg-secondary text-foreground",
      projected: nrrHasData
        ? "Projection, not an actual. Mean projected NRR on the most recent decided episodes, derived from the outcome simulator weighted by confidence and the recorded human decision."
        : undefined,
    },
    {
      label: "NRR uplift / qtr",
      value:
        evalReport && evalUplift !== null
          ? `${evalUplift >= 0 ? "+" : ""}${evalUplift.toFixed(1)} pts`
          : "--",
      sub: evalReport
        ? `${evalReport.outcomes.projected}% vs ${evalReport.outcomes.baseline}% baseline`
        : "Projected from accepted plays",
      icon: ArrowUpRight,
      tone: "bg-primary/10 text-primary",
      projected:
        "Projection from the outcome simulator across the seed accounts, weighted by engine confidence and real acceptance. Baseline is a manual-triage reference, not a measured control.",
    },
  ];

  const loaded = accounts && learning && evalReport;

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-eyebrow">Overview</div>
          <h1 className="mt-1 text-display">Decision command center</h1>
          <p className="mt-1.5 max-w-xl text-sm text-muted-foreground">
            Every recommendation is evidence-backed, confidence-scored, and
            gated by human approval. Start where the risk is highest.
          </p>
        </div>
        <Button asChild size="lg">
          <Link href="/run">
            New run
            <ArrowRight className="ml-1 h-4 w-4" />
          </Link>
        </Button>
      </header>

      {error ? (
        <div className="panel mt-2">
          <ErrorState onRetry={retry} />
        </div>
      ) : (
        <>
      {loaded && !hasRuns ? (
        <div className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-dashed border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">
            Outcomes populate after runs.
          </span>
          <span>
            Run{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">
              make gen-runs
            </code>{" "}
            (or work the inbox and approve recommendations) to record real
            decisions; acceptance, the learning trend, and projected NRR fill in
            from there.
          </span>
        </div>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {loaded
          ? kpis.map((kpi) => <KpiCard key={kpi.label} kpi={kpi} />)
          : Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="panel p-5">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="mt-4 h-8 w-20" />
                <Skeleton className="mt-2 h-3 w-32" />
              </div>
            ))}
      </section>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <section className="panel overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
            <h2 className="text-sm font-semibold">Highest-risk accounts</h2>
            <Link
              href="/inbox"
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Open inbox
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <div className="divide-y divide-border">
            {accounts === null ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-5 py-3.5">
                  <Skeleton className="h-9 w-9 rounded-full" />
                  <div className="flex-1">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="mt-1.5 h-3 w-56" />
                  </div>
                </div>
              ))
            ) : recentRisk.length === 0 ? (
              <EmptyState
                icon={Building2}
                title="No accounts yet"
                description="Connect a data source or seed the workspace to start triaging risk."
              />
            ) : (
              recentRisk.map((a) => (
                  <Link
                    key={a.account_id}
                    href={`/accounts/${a.account_id}`}
                    className="flex items-center gap-3 px-5 py-3.5 transition-colors hover:bg-accent/40"
                  >
                    <span
                      className={cn(
                        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular",
                        a.health_score >= 70
                          ? "bg-muted text-foreground"
                          : a.health_score >= 45
                            ? "bg-primary/12 text-primary"
                            : "bg-destructive/12 text-destructive",
                      )}
                    >
                      {a.health_score}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium">{a.name}</span>
                        <Badge variant={riskVariant(a.risk_level)}>
                          {String(a.risk_level)}
                        </Badge>
                      </div>
                      <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                        {a.last_signal}
                      </p>
                    </div>
                    <span className="shrink-0 text-sm font-medium tabular text-muted-foreground">
                      {formatArr(a.arr)}
                    </span>
                  </Link>
                ))
            )}
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold">Jump back in</h2>
          {QUICK_LINKS.map((link) => {
            const Icon = link.icon;
            return (
              <Link
                key={link.href}
                href={link.href}
                className="group flex items-start gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/30"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-foreground">
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{link.label}</span>
                    <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {link.desc}
                  </p>
                </div>
              </Link>
            );
          })}
        </section>
      </div>
        </>
      )}
    </div>
  );
}
