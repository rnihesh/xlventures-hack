"use client";

import { useMemo, useState } from "react";
import {
  ArrowRight,
  Minus,
  RotateCcw,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfidenceDial } from "@/components/confidence-dial";
import { cn } from "@/lib/utils";
import { whatIf, type WhatIfResponse } from "@/lib/api";
import type { Recommendation } from "@/lib/types";

interface WhatIfPanelProps {
  domain: string;
  accountId: string;
  // The live/seed baseline recommendation, used to seed defaults and show the
  // confidence the what-if is compared against.
  baseline?: Recommendation | null;
  className?: string;
}

interface SliderRowProps {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}

function SliderRow({
  label,
  hint,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: SliderRowProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label className="text-sm font-medium text-foreground">{label}</label>
        <span className="text-sm font-semibold tabular-nums text-foreground">
          {format(value)}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-2 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
        aria-label={label}
      />
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

function DeltaPill({ delta }: { delta: number }) {
  const pts = Math.round(delta * 100);
  const tone =
    pts > 0 ? "success" : pts < 0 ? "danger" : "muted";
  const Icon = pts > 0 ? TrendingUp : pts < 0 ? TrendingDown : Minus;
  return (
    <Badge variant={tone}>
      <Icon className="size-3" />
      {pts > 0 ? "+" : ""}
      {pts} pts confidence
    </Badge>
  );
}

export function WhatIfPanel({
  domain,
  accountId,
  baseline,
  className,
}: WhatIfPanelProps) {
  // Seed slider defaults from the baseline story when available.
  const defaults = useMemo(() => {
    const arr = 180000;
    return { usageTrend: -10, nps: 7, arr };
  }, []);

  const [usageTrend, setUsageTrend] = useState(defaults.usageTrend);
  const [nps, setNps] = useState(defaults.nps);
  const [arr, setArr] = useState(defaults.arr);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WhatIfResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const baselineConfidence =
    result?.baseline.confidence ?? baseline?.confidence.score ?? null;

  async function rePlan() {
    setLoading(true);
    setError(null);
    try {
      const res = await whatIf({
        domain,
        account_id: accountId,
        overrides: { usage_trend: usageTrend, nps, arr },
      });
      setResult(res);
    } catch {
      setError("Could not re-plan. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setUsageTrend(defaults.usageTrend);
    setNps(defaults.nps);
    setArr(defaults.arr);
    setResult(null);
    setError(null);
  }

  const newConfidence = result?.recommendation.confidence.score ?? null;
  const delta = result?.confidence_delta ?? 0;

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" />
            <CardTitle className="text-lg">What-if analysis</CardTitle>
          </div>
          <Badge variant="muted">Counterfactual</Badge>
        </div>
        <CardDescription>
          Nudge the input signals and re-plan to see how the next best action and
          its confidence change.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="space-y-4">
          <SliderRow
            label="Usage trend (QoQ)"
            hint="How product usage is trending quarter over quarter. Negative means decline."
            value={usageTrend}
            min={-50}
            max={50}
            step={1}
            format={(v) => `${v >= 0 ? "+" : ""}${v}%`}
            onChange={setUsageTrend}
          />
          <SliderRow
            label="NPS"
            hint="Latest net promoter score on a 0 to 10 scale."
            value={nps}
            min={0}
            max={10}
            step={1}
            format={(v) => `${v}/10`}
            onChange={setNps}
          />
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <label
                htmlFor="whatif-arr"
                className="text-sm font-medium text-foreground"
              >
                Contract size (ARR)
              </label>
              <span className="text-sm font-semibold tabular-nums text-foreground">
                ${arr.toLocaleString("en-US")}
              </span>
            </div>
            <Input
              id="whatif-arr"
              type="number"
              min={0}
              step={10000}
              value={arr}
              onChange={(e) => setArr(Number(e.target.value) || 0)}
            />
            <p className="text-xs text-muted-foreground">
              Annual recurring revenue at stake on this account.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button onClick={rePlan} disabled={loading} className="flex-1">
            <Sparkles className="size-4" />
            {loading ? "Re-planning..." : "Re-plan"}
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={reset}
            disabled={loading}
            aria-label="Reset to baseline"
          >
            <RotateCcw className="size-4" />
          </Button>
        </div>

        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}

        {result ? (
          <>
            <Separator />
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Re-planned recommendation
                </span>
                {result.action_changed ? (
                  <Badge variant="warning">Action changed</Badge>
                ) : (
                  <Badge variant="muted">Action held</Badge>
                )}
              </div>

              <div className="flex items-start gap-4">
                <ConfidenceDial
                  value={newConfidence ?? 0}
                  sublabel="conf"
                  size={84}
                  thickness={7}
                />
                <div className="min-w-0 flex-1 space-y-2">
                  {result.action_changed && result.baseline.action?.title ? (
                    <div className="flex flex-wrap items-center gap-1.5 text-sm">
                      <span className="text-muted-foreground line-through">
                        {result.baseline.action.title}
                      </span>
                      <ArrowRight className="size-3.5 text-muted-foreground" />
                      <span className="font-semibold text-foreground">
                        {result.recommendation.action.title}
                      </span>
                    </div>
                  ) : (
                    <p className="text-sm font-semibold text-foreground">
                      {result.recommendation.action.title}
                    </p>
                  )}
                  <p className="text-sm text-muted-foreground">
                    {result.recommendation.action.description}
                  </p>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <DeltaPill delta={delta} />
                    {baselineConfidence != null ? (
                      <span className="text-xs text-muted-foreground tabular-nums">
                        {Math.round(baselineConfidence * 100)}% baseline{" "}
                        <ArrowRight className="inline size-3 align-[-1px]" />{" "}
                        {Math.round((newConfidence ?? 0) * 100)}% now
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-md border border-border bg-muted/40 p-3">
                  <p className="text-xs text-muted-foreground">Churn risk</p>
                  <p className="text-sm font-semibold tabular-nums text-foreground">
                    {result.risk_score.baseline.toFixed(2)}
                    <ArrowRight className="mx-1 inline size-3 align-[-1px] text-muted-foreground" />
                    {result.risk_score.whatif.toFixed(2)}
                  </p>
                </div>
                <div className="rounded-md border border-border bg-muted/40 p-3">
                  <p className="text-xs text-muted-foreground">Inputs applied</p>
                  <p className="text-sm font-semibold tabular-nums text-foreground">
                    {signPct(result.applied_overrides.usage_trend)} |{" "}
                    {result.applied_overrides.nps.toFixed(0)}/10
                  </p>
                </div>
              </div>

              {result.recommendation.counterfactual ? (
                <p className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
                  {result.recommendation.counterfactual}
                </p>
              ) : null}
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

function signPct(v: number): string {
  return `${v >= 0 ? "+" : ""}${Math.round(v)}%`;
}

export default WhatIfPanel;
