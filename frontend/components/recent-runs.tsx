"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { History, ChevronRight } from "lucide-react";

import { getRuns, type RunSummary } from "@/lib/api/runs";

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

// Recent NBA runs for this workspace. A run that produced a recommendation links
// to its account 360 (where the decision, evidence, and brief live). Refreshes
// when `refreshKey` changes so a just-finished run appears.
export function RecentRuns({ refreshKey }: { refreshKey?: number }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    void getRuns(ctrl.signal).then(setRuns);
    return () => ctrl.abort();
  }, [refreshKey]);

  if (runs !== null && runs.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center gap-2 text-sm font-medium">
          <History className="h-4 w-4 text-primary" />
          Recent runs
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          No runs yet. Run an NBA above and it will appear here, stored against
          its account.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border px-5 py-3.5 text-sm font-medium">
        <History className="h-4 w-4 text-primary" />
        Recent runs
        {runs ? (
          <span className="text-xs font-normal text-muted-foreground">
            {runs.length}
          </span>
        ) : null}
      </div>
      <ul className="divide-y divide-border">
        {(runs ?? []).map((r) => {
          const body = (
            <div className="flex items-center justify-between gap-3 px-5 py-3.5 transition-colors hover:bg-accent/40">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">
                    {r.action_title || "No recommendation"}
                  </span>
                  {typeof r.confidence === "number" ? (
                    <span className="shrink-0 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                      {Math.round(r.confidence * 100)}%
                    </span>
                  ) : null}
                </div>
                <div className="mt-0.5 truncate text-xs text-muted-foreground">
                  {r.account_name || r.account_id
                    ? `${r.account_name || r.account_id} · `
                    : ""}
                  {r.signal_summary || r.domain || ""}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="text-[11px] text-muted-foreground">
                  {timeAgo(r.created_at)}
                </span>
                {r.account_id ? (
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                ) : null}
              </div>
            </div>
          );
          return (
            <li key={r.run_id}>
              {r.account_id ? (
                <Link href={`/accounts/${encodeURIComponent(r.account_id)}`}>
                  {body}
                </Link>
              ) : (
                body
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default RecentRuns;
