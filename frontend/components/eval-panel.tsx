"use client";

import {
  CheckCircle2,
  XCircle,
  CircleDashed,
  Target,
  ArrowRight,
  History,
  Info,
} from "lucide-react";

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
  healthy?: boolean; // backend verdict; preferred over a strict passed===total check
  no_data?: boolean; // org-scoped suite with no data yet (awaiting, not failing)
}

export interface EvalOutcomes {
  kpi: string;
  baseline: number | string;
  projected: number | string;
  unit?: string;
}

// Optional projection detail from /eval. The PROJECTED figures are labeled
// projections: the dollar value is the real at-risk ARR of this org's accounts
// multiplied by the projected save-rate lift, not a measured actual. The
// REALISED block is the learning-loop side: real human decisions and the real
// ARR they cover, honestly empty until decisions exist.
export interface EvalRealised {
  has_data?: boolean;
  source?: string;
  accepted_plays?: number;
  decided?: number;
  acceptance_rate?: number;
  arr_under_accepted?: number;
  tracked_nrr?: number | null;
  baseline_nrr?: number;
  nrr_lift?: number | null;
  note?: string;
}

export interface EvalBreakdown {
  projected?: boolean;
  no_data?: boolean;
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
  realised?: EvalRealised;
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
  const { outcomes, breakdown } = data;
  const arr = breakdown?.arr_at_risk;
  const addressed =
    typeof arr?.addressed === "number" ? arr.addressed : null;
  const acceptance = breakdown?.acceptance;
  const realised = breakdown?.realised;
  const noData = breakdown?.no_data === true;
  const method =
    breakdown?.method ??
    "Projection from the outcome simulator across this org's accounts, weighted by engine confidence and real acceptance. Baseline is a manual-triage reference, not a measured control.";
  const acceptRate =
    typeof realised?.acceptance_rate === "number"
      ? realised.acceptance_rate
      : typeof acceptance?.rate === "number"
        ? acceptance.rate
        : null;

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
              Accounts at risk
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tabular-nums">
              {arr?.accounts ?? 0}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">
              ARR at risk addressed
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tabular-nums text-primary">
              {addressed !== null ? formatUsd(addressed) : "$0"}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">
              Acceptance rate
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tabular-nums">
              {acceptRate !== null ? `${Math.round(acceptRate * 100)}%` : "--"}
              <span className="ml-1 block text-[11px] font-normal text-muted-foreground">
                {realised?.decided
                  ? `across ${realised.decided} decisions`
                  : "no decisions yet"}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

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
            {noData ? (
              <div className="mb-1 inline-flex items-center gap-1 rounded-full bg-secondary px-2.5 py-1 text-xs font-medium text-muted-foreground ring-1 ring-inset ring-border">
                Awaiting data
              </div>
            ) : delta !== null ? (
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
                    real, this org&apos;s at-risk accounts
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

          {/* How this is computed: methodology, kept legible and honest. */}
          <div className="mt-5 flex gap-2 rounded-lg border border-border bg-secondary/40 px-3.5 py-3">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold text-foreground">
                How this is computed
              </span>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {method}
              </p>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                Per account: simulator impact x adoption x engine confidence x
                realisation factor, sized by the ARR of this org&apos;s at-risk
                accounts. Adoption uses the org&apos;s real acceptance once
                decisions exist, otherwise mean confidence. These figures are a
                labeled projection, not a measured control.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Realised: the learning-loop side, real human decisions */}
      <Card>
        <CardHeader className="pb-3">
          <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <History className="h-3.5 w-3.5" />
            Realised, learning loop
            <span className="ml-auto rounded-full bg-secondary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
              {realised?.has_data ? "Measured decisions" : "Awaiting data"}
            </span>
          </CardDescription>
          <CardTitle className="text-base">
            Plays accepted and tracked
          </CardTitle>
        </CardHeader>
        <CardContent>
          {realised?.has_data ? (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="flex flex-col">
                  <span className="text-xs text-muted-foreground">
                    Accepted plays
                  </span>
                  <span className="font-mono text-2xl font-semibold tabular text-foreground">
                    {realised.accepted_plays ?? 0}
                    <span className="text-sm text-muted-foreground">
                      /{realised.decided ?? 0}
                    </span>
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    real human decisions
                    {typeof realised.acceptance_rate === "number"
                      ? `, ${Math.round(realised.acceptance_rate * 100)}% accepted`
                      : ""}
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="text-xs text-muted-foreground">
                    ARR under accepted plays
                  </span>
                  <span className="font-mono text-2xl font-semibold tabular text-primary">
                    {formatUsd(realised.arr_under_accepted ?? 0)}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    real account ARR
                  </span>
                </div>
                {typeof realised.tracked_nrr === "number" ? (
                  <div className="flex flex-col">
                    <span
                      className="cursor-help text-xs text-muted-foreground"
                      title="Projected NRR recorded against the accepted plays at decision time. A tracked projection, not a measured actual."
                    >
                      Tracked NRR
                    </span>
                    <span className="font-mono text-2xl font-semibold tabular text-foreground">
                      {realised.tracked_nrr.toFixed(1)}
                      <span className="ml-1 text-sm font-normal text-muted-foreground">
                        %
                      </span>
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {typeof realised.nrr_lift === "number"
                        ? `${realised.nrr_lift >= 0 ? "+" : ""}${realised.nrr_lift.toFixed(1)} vs baseline, projected`
                        : "projected"}
                    </span>
                  </div>
                ) : null}
              </div>
              {realised.note ? (
                <p className="mt-4 border-t border-border pt-3 text-[11px] leading-relaxed text-muted-foreground">
                  {realised.note}
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-xs leading-relaxed text-muted-foreground">
              {realised?.note ??
                "No accepted plays recorded for this org yet. Approve or edit recommendations to populate the realised learning-loop numbers from real outcomes."}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default EvalPanel;
