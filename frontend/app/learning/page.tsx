"use client";

import { useEffect, useState } from "react";
import { GraduationCap, Inbox } from "lucide-react";

import { LearningPanel, type LearningData } from "@/components/learning-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { getLearning } from "@/lib/api";

// No fabricated fallback: the learning loop starts empty and fills from real
// runs only. On load failure we surface an honest empty state, never invented
// before/after numbers.
const EMPTY: LearningData = {
  accepted_rate: 0,
  trend: [],
  decided: 0,
  before_after: {
    kpi: "Net Revenue Retention (projected %)",
    before: 0,
    after: 0,
    note: "No runs yet.",
    has_data: false,
    projected: true,
  },
  episodes: [],
};

export default function LearningPage() {
  const [data, setData] = useState<LearningData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = (await getLearning()) as LearningData;
        if (alive && res && Array.isArray(res.episodes)) {
          setData(res);
        } else if (alive) {
          setData(EMPTY);
        }
      } catch {
        if (alive) setData(EMPTY);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const isEmpty = !!data && data.episodes.length === 0;

  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
            <GraduationCap className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-sm font-medium text-muted-foreground">
              Learning
            </h1>
            <p className="text-lg font-semibold tracking-tight">
              Memory and the feedback loop
            </p>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-5xl px-6 py-8">
        {loading || !data ? (
          <div className="grid gap-4 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-40 rounded-lg" />
            ))}
          </div>
        ) : isEmpty ? (
          <EmptyLearning />
        ) : (
          <LearningPanel data={data} />
        )}
      </div>
    </div>
  );
}

function EmptyLearning() {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-6 py-20 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Inbox className="h-6 w-6" />
      </div>
      <h2 className="mt-5 text-lg font-semibold tracking-tight">
        No runs yet
      </h2>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
        Approve or reject recommendations to start the learning loop, or run{" "}
        <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">
          make gen-runs
        </code>{" "}
        to drive a batch of real runs through the planner. As outcomes are
        recorded, the recommender distills them into preferences and the
        acceptance trend and projected NRR delta appear here, computed from
        actual decisions, never a fabricated baseline.
      </p>
      <div className="mt-6 grid w-full max-w-md grid-cols-3 gap-3 text-left">
        {[
          { k: "Episodes", v: "0" },
          { k: "Acceptance", v: "--" },
          { k: "NRR delta", v: "--" },
        ].map((s) => (
          <div
            key={s.k}
            className="rounded-lg border border-border bg-background/60 p-3"
          >
            <div className="text-xs text-muted-foreground">{s.k}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums">{s.v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
