"use client";

import { CheckCircle2, XCircle, Target, ArrowRight } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface EvalSuite {
  name: string;
  metric: string;
  score: number; // 0..1
  passed: number;
  total: number;
}

export interface EvalOutcomes {
  kpi: string;
  baseline: number | string;
  projected: number | string;
  unit?: string;
}

// Optional projection detail from /eval. Every figure here is a labeled
// projection: the dollar value is the real at-risk ARR (from the seed corpus)
// multiplied by the projected save-rate lift, not a measured actual.
export interface EvalBreakdown {
  projected?: boolean;
  method?: string;
  acceptance?: {
    rate?: number;
    source?: string;
    measured?: boolean;
    decided?: number;
  };
  arr_at_risk?: {
    total?: number;
    accounts?: number;
    addressed?: number;
    projected_save_rate?: number;
    baseline_save_rate?: number;
  };
}

export interface EvalData {
  suites: EvalSuite[];
  outcomes: EvalOutcomes;
  breakdown?: EvalBreakdown;
}

function formatUsd(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (Math.abs(v) >= 1_000) return `$${Math.round(v / 1_000)}K`;
  return `$${Math.round(v)}`;
}

function scoreTone(v: number) {
  if (v >= 0.65) return "bg-primary";
  return "bg-destructive";
}

function numeric(v: number | string): number | null {
  if (typeof v === "number") return v;
  const n = parseFloat(v.replace(/[^0-9.\-]/g, ""));
  return Number.isFinite(n) ? n : null;
}

export function EvalPanel({ data }: { data: EvalData }) {
  const { suites, outcomes, breakdown } = data;
  const arr = breakdown?.arr_at_risk;
  const addressed =
    typeof arr?.addressed === "number" ? arr.addressed : null;
  const acceptance = breakdown?.acceptance;
  const method =
    breakdown?.method ??
    "Projection from the outcome simulator across the seed accounts, weighted by engine confidence and real acceptance. Baseline is a manual-triage reference, not a measured control.";
  const passedCount = suites.filter((s) => s.passed >= s.total && s.total > 0).length;
  const overall =
    suites.length > 0
      ? suites.reduce((a, s) => a + s.score, 0) / suites.length
      : 0;

  const base = numeric(outcomes.baseline);
  const proj = numeric(outcomes.projected);
  const hasDelta = base !== null && proj !== null;
  const delta = hasDelta ? proj! - base! : null;
  const up = delta !== null ? delta >= 0 : true;
  const unit = outcomes.unit || "";

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">
              Suites passing
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tabular-nums">
              {passedCount}
              <span className="text-lg text-muted-foreground">
                /{suites.length}
              </span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">
              Mean score
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div
              className={cn(
                "text-3xl font-semibold tabular-nums",
                overall >= 0.65 ? "text-primary" : "text-destructive"
              )}
            >
              {Math.round(overall * 100)}%
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">
              Checks evaluated
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tabular-nums">
              {suites.reduce((a, s) => a + s.total, 0)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Suites table with score bars */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Evaluation suites</CardTitle>
          <CardDescription>
            Offline checks run against the recommender before anything ships.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="divide-y divide-border">
            {suites.map((s) => {
              const pass = s.total > 0 && s.passed >= s.total;
              return (
                <div
                  key={s.name}
                  className="grid grid-cols-12 items-center gap-3 px-6 py-3.5"
                >
                  <div className="col-span-12 sm:col-span-4">
                    <div className="flex items-center gap-2">
                      {pass ? (
                        <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
                      ) : (
                        <XCircle className="h-4 w-4 shrink-0 text-destructive" />
                      )}
                      <span className="truncate font-medium">{s.name}</span>
                    </div>
                    <span className="ml-6 text-xs text-muted-foreground">
                      {s.metric}
                    </span>
                  </div>
                  <div className="col-span-8 sm:col-span-6">
                    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all duration-700",
                          scoreTone(s.score)
                        )}
                        style={{
                          width: `${Math.round(
                            Math.max(0, Math.min(1, s.score)) * 100
                          )}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div className="col-span-4 flex items-center justify-end gap-3 sm:col-span-2">
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {s.passed}/{s.total}
                    </span>
                    <span className="w-10 text-right text-sm font-semibold tabular-nums">
                      {Math.round(s.score * 100)}%
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Outcomes: baseline vs projected */}
      <Card className="border-primary/30 bg-primary/[0.03]">
        <CardHeader className="pb-3">
          <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-primary">
            <Target className="h-3.5 w-3.5" />
            Projected business outcome
            <span
              className="ml-auto cursor-help rounded-full bg-secondary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground"
              title={method}
            >
              Projected
            </span>
          </CardDescription>
          <CardTitle className="text-base">{outcomes.kpi}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-6">
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">Baseline</span>
              <span className="font-mono text-2xl font-semibold tabular text-muted-foreground">
                {String(outcomes.baseline)}
                {unit ? (
                  <span className="ml-1 text-sm font-normal">{unit}</span>
                ) : null}
              </span>
            </div>
            <ArrowRight className="mb-2 h-5 w-5 text-muted-foreground" />
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">
                With Aperture
              </span>
              <span
                className={cn(
                  "font-mono text-4xl font-semibold tabular",
                  up ? "text-primary" : "text-destructive"
                )}
              >
                {String(outcomes.projected)}
                {unit ? (
                  <span className="ml-1 text-base font-normal">{unit}</span>
                ) : null}
              </span>
            </div>
            {delta !== null ? (
              <div
                className={cn(
                  "mb-1 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
                  up
                    ? "bg-primary/10 text-primary ring-primary/20"
                    : "bg-destructive/10 text-destructive ring-destructive/20"
                )}
              >
                {up ? "+" : ""}
                {Math.abs(delta) < 1 ? delta.toFixed(2) : delta.toFixed(1)}
                {unit ? ` ${unit}` : ""} projected
              </div>
            ) : null}
          </div>

          {addressed !== null ? (
            <div className="mt-5 grid gap-4 border-t border-border pt-4 sm:grid-cols-3">
              <div className="flex flex-col">
                <span
                  className="cursor-help text-xs text-muted-foreground"
                  title="Real ARR of the at-risk seed accounts multiplied by the projected save-rate lift over the manual-triage baseline."
                >
                  ARR at risk addressed
                </span>
                <span className="font-mono text-2xl font-semibold tabular text-primary">
                  {formatUsd(addressed)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  projected, from {arr?.accounts ?? 0} at-risk accounts
                </span>
              </div>
              {typeof arr?.total === "number" ? (
                <div className="flex flex-col">
                  <span className="text-xs text-muted-foreground">
                    Total ARR at risk
                  </span>
                  <span className="font-mono text-2xl font-semibold tabular text-muted-foreground">
                    {formatUsd(arr.total)}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    real, from the seed corpus
                  </span>
                </div>
              ) : null}
              {acceptance && typeof acceptance.rate === "number" ? (
                <div className="flex flex-col">
                  <span className="text-xs text-muted-foreground">
                    Acceptance weighting
                  </span>
                  <span className="font-mono text-2xl font-semibold tabular text-foreground">
                    {Math.round(acceptance.rate * 100)}%
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    {acceptance.measured
                      ? `measured, ${acceptance.decided ?? 0} decisions`
                      : "modeled from confidence (no runs yet)"}
                  </span>
                </div>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

export default EvalPanel;
