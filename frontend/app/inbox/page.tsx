"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Inbox as InboxIcon, Play, Radar, SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { riskVariant, formatArr, healthTone } from "@/components/account-table";
import { cn } from "@/lib/utils";
import { getAccounts } from "@/lib/api";
import type { Account } from "@/lib/types";

const RISK_ORDER: Record<string, number> = { high: 3, medium: 2, low: 1 };
const FILTERS = ["all", "high", "medium", "low"] as const;
type Filter = (typeof FILTERS)[number];

function runHref(account: Account): string {
  const params = new URLSearchParams({
    account_id: account.account_id,
    domain: account.domain,
    signal: account.last_signal,
  });
  return `/run?${params.toString()}`;
}

function TriageRow({ account }: { account: Account }) {
  return (
    <div className="group flex flex-col gap-3 px-5 py-4 transition-colors hover:bg-accent/30 sm:flex-row sm:items-center">
      <span
        aria-hidden
        className={cn(
          "mt-1 h-2.5 w-2.5 shrink-0 rounded-full sm:mt-0",
          healthTone(account.health_score),
        )}
      />

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={`/accounts/${account.account_id}`}
            className="font-medium text-foreground hover:underline"
          >
            {account.name}
          </Link>
          <Badge variant={riskVariant(account.risk_level)}>
            {String(account.risk_level)} risk
          </Badge>
          <span className="text-xs text-muted-foreground">
            health {account.health_score} · {formatArr(account.arr)} ARR
          </span>
        </div>
        <p className="mt-1 flex items-start gap-1.5 text-sm text-muted-foreground">
          <Radar className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
          <span className="line-clamp-2">{account.last_signal}</span>
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <Button asChild variant="outline" size="sm">
          <Link href={`/accounts/${account.account_id}`}>360</Link>
        </Button>
        <Button asChild size="sm">
          <Link href={runHref(account)}>
            <Play className="h-3.5 w-3.5" />
            Run NBA
          </Link>
        </Button>
      </div>
    </div>
  );
}

export default function InboxPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState(false);
  const [nonce, setNonce] = useState(0);

  const retry = useCallback(() => {
    setError(false);
    setAccounts(null);
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void getAccounts(ctrl.signal)
      .then(setAccounts)
      .catch((err) => {
        if (err?.name !== "AbortError") setError(true);
      });
    return () => ctrl.abort();
  }, [nonce]);

  const queue = useMemo(() => {
    if (!accounts) return [];
    const rows =
      filter === "all"
        ? accounts
        : accounts.filter(
            (a) => String(a.risk_level).toLowerCase() === filter,
          );
    return [...rows].sort((a, b) => {
      const r =
        (RISK_ORDER[String(b.risk_level).toLowerCase()] ?? 0) -
        (RISK_ORDER[String(a.risk_level).toLowerCase()] ?? 0);
      if (r !== 0) return r;
      return a.health_score - b.health_score;
    });
  }, [accounts, filter]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: accounts?.length ?? 0 };
    for (const a of accounts ?? []) {
      const k = String(a.risk_level).toLowerCase();
      c[k] = (c[k] ?? 0) + 1;
    }
    return c;
  }, [accounts]);

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-eyebrow">Triage</div>
          <h1 className="mt-1 text-display">Inbox</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Accounts with fresh signals that need a next best action, ranked by
            risk then health.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/accounts">
            All accounts
            <ArrowRight className="ml-1 h-4 w-4" />
          </Link>
        </Button>
      </header>

      <div className="mb-4 flex items-center gap-2">
        <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                filter === f
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {f}
              <span className="ml-1.5 tabular opacity-70">
                {counts[f] ?? 0}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="panel divide-y divide-border overflow-hidden">
        {error ? (
          <ErrorState onRetry={retry} />
        ) : accounts === null ? (
          Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 px-5 py-4">
              <Skeleton className="h-2.5 w-2.5 rounded-full" />
              <div className="flex-1">
                <Skeleton className="h-4 w-44" />
                <Skeleton className="mt-2 h-3 w-72" />
              </div>
              <Skeleton className="h-8 w-24" />
            </div>
          ))
        ) : queue.length === 0 ? (
          <EmptyState
            icon={InboxIcon}
            title="Inbox zero"
            description={
              filter === "all"
                ? "No accounts need a next best action right now."
                : `No ${filter}-risk accounts in the queue. Try another filter.`
            }
          />
        ) : (
          queue.map((account) => (
            <TriageRow key={account.account_id} account={account} />
          ))
        )}
      </div>
    </div>
  );
}
