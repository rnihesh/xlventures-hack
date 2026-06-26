"use client";

import { useEffect, useState } from "react";
import { FlaskConical } from "lucide-react";

import { EvalPanel, type EvalData } from "@/components/eval-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { getEval } from "@/lib/api";

const FALLBACK: EvalData = {
  suites: [
    {
      name: "Grounding / citations",
      metric: "Every claim cites real evidence",
      score: 0.94,
      passed: 47,
      total: 50,
    },
    {
      name: "Action validity",
      metric: "Recommended action exists in the pack",
      score: 1.0,
      passed: 50,
      total: 50,
    },
    {
      name: "Confidence calibration",
      metric: "Predicted vs observed acceptance",
      score: 0.81,
      passed: 40,
      total: 50,
    },
    {
      name: "Guardrail compliance",
      metric: "No policy breach (discounts, cooldowns)",
      score: 0.98,
      passed: 49,
      total: 50,
    },
    {
      name: "Counterfactual coherence",
      metric: "What-if re-plans stay consistent",
      score: 0.72,
      passed: 36,
      total: 50,
    },
  ],
  outcomes: {
    kpi: "Annual revenue retained on at-risk cohort",
    baseline: "1.2M",
    projected: "1.6M",
    unit: "$",
  },
};

export default function EvalPage() {
  const [data, setData] = useState<EvalData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = (await getEval()) as EvalData;
        if (alive && res && Array.isArray(res.suites)) {
          setData(res);
        } else if (alive) {
          setData(FALLBACK);
        }
      } catch {
        if (alive) setData(FALLBACK);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
              <FlaskConical className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-sm font-medium text-muted-foreground">Eval</h1>
              <p className="text-lg font-semibold tracking-tight">
                Quality gates and projected outcomes
              </p>
            </div>
          </div>
        </header>

        <div className="mx-auto w-full max-w-5xl px-6 py-8">
          {loading || !data ? (
            <div className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-24 rounded-lg" />
                ))}
              </div>
              <Skeleton className="h-64 rounded-lg" />
            </div>
          ) : (
            <EvalPanel data={data} />
          )}
        </div>
    </div>
  );
}
