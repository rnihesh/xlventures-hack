"use client";

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";

import { EvalPanel, type EvalData } from "@/components/eval-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page-header";
import { getEval } from "@/lib/api";

export default function EvalPage() {
  // No hardcoded fallback numbers: every score and outcome is computed by the
  // backend eval runner over golden cases. On failure we show an honest error
  // state rather than fabricated metrics.
  const [data, setData] = useState<EvalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = (await getEval()) as EvalData;
        if (alive && res && Array.isArray(res.suites)) {
          setData(res);
        } else if (alive) {
          setFailed(true);
        }
      } catch {
        if (alive) setFailed(true);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-8">
      <PageHeader
        eyebrow="Insight"
        title="Evaluation"
        description="Projected and realised business outcomes for this workspace, from its accounts and recorded decisions."
      />

      <div>
        {loading ? (
          <div className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-24 rounded-lg" />
              ))}
            </div>
            <Skeleton className="h-64 rounded-lg" />
          </div>
        ) : failed || !data ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-6 py-20 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-muted-foreground">
              <AlertTriangle className="h-6 w-6" />
            </div>
            <h2 className="mt-5 text-lg font-semibold tracking-tight">
              Evaluation unavailable
            </h2>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
              The outcomes service could not be reached, so no numbers are shown.
            </p>
          </div>
        ) : (
          <EvalPanel data={data} />
        )}
      </div>
    </div>
  );
}
