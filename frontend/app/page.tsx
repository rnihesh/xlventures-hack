"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
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
      <div className="mt-3 text-3xl font-semibold tracking-tight tabular">
        {kpi.value}
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{kpi.sub}</p>
    </div>
  );
}

export default function OverviewPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [learning, setLearning] = useState<Learning | null>(null);
  const [evalReport, setEvalReport] = useState<EvalReport | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    void Promise.all([
      getAccounts(ctrl.signal),
      getLearning(ctrl.signal),
      getEval(ctrl.signal),
    ]).then(([a, l, e]) => {
      setAccounts(a);
      setLearning(l);
      setEvalReport(e);
    });
    return () => ctrl.abort();
  }, []);

  const atRisk = accounts?.filter(
    (a) => String(a.risk_level).toLowerCase() === "high",
  );
  const arrAtRisk = atRisk?.reduce((sum, a) => sum + a.arr, 0) ?? 0;
  const recentRisk = [...(accounts ?? [])]
    .sort((a, b) => a.health_score - b.health_score)
    .slice(0, 5);

  const kpis: Kpi[] = [
    {
      label: "Accounts at risk",
      value: atRisk ? String(atRisk.length) : "--",
      sub: `${formatArr(arrAtRisk)} ARR exposed`,
      icon: AlertTriangle,
      tone: "bg-rose-500/12 text-rose-500",
    },
    {
      label: "Acceptance rate",
      value: learning ? `${Math.round(learning.accepted_rate * 100)}%` : "--",
      sub: "Recommendations approved by reps",
      icon: CheckCircle2,
      tone: "bg-emerald-500/12 text-emerald-500",
    },
    {
      label: "NRR projected",
      value: learning ? `${learning.before_after.after}%` : "--",
      sub: learning
        ? `Up from ${learning.before_after.before}% baseline`
        : "Learning loop warming up",
      icon: TrendingUp,
      tone: "bg-indigo-500/12 text-indigo-500",
    },
    {
      label: "ARR protected / qtr",
      value: evalReport
        ? `${evalReport.outcomes.projected}${evalReport.outcomes.unit}`
        : "--",
      sub: evalReport
        ? `vs ${evalReport.outcomes.baseline}${evalReport.outcomes.unit} baseline`
        : "Projected from accepted plays",
      icon: ArrowUpRight,
      tone: "bg-sky-500/12 text-sky-500",
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
            {recentRisk.length === 0
              ? Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3 px-5 py-3.5">
                    <Skeleton className="h-9 w-9 rounded-full" />
                    <div className="flex-1">
                      <Skeleton className="h-4 w-40" />
                      <Skeleton className="mt-1.5 h-3 w-56" />
                    </div>
                  </div>
                ))
              : recentRisk.map((a) => (
                  <Link
                    key={a.account_id}
                    href={`/accounts/${a.account_id}`}
                    className="flex items-center gap-3 px-5 py-3.5 transition-colors hover:bg-accent/40"
                  >
                    <span
                      className={cn(
                        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular",
                        a.health_score >= 70
                          ? "bg-emerald-500/12 text-emerald-500"
                          : a.health_score >= 45
                            ? "bg-amber-500/12 text-amber-500"
                            : "bg-rose-500/12 text-rose-500",
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
                ))}
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
    </div>
  );
}
