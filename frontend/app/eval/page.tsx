"use client";

import { useEffect, useState } from "react";
import { FlaskConical, AlertTriangle } from "lucide-react";

import { EvalPanel, type EvalData } from "@/components/eval-panel";
import { Skeleton } from "@/components/ui/skeleton";
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
              The eval runner could not be reached. Scores are computed over the
              golden cases on the backend, so no numbers are shown until a run
              succeeds.
            </p>
          </div>
        ) : (
          <EvalPanel data={data} />
        )}
      </div>
    </div>
  );
}
