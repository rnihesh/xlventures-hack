"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  CalendarClock,
  CircleUser,
  Play,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { riskVariant, formatArr, healthTone } from "@/components/account-table";
import { cn } from "@/lib/utils";
import { getAccount } from "@/lib/api";
import type { AccountDetail, AccountSignal, Recommendation } from "@/lib/types";

function fmtDate(value?: string): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function severityVariant(
  sev?: string,
): "danger" | "warning" | "info" | "muted" {
  switch (String(sev).toLowerCase()) {
    case "high":
      return "danger";
    case "medium":
      return "warning";
    case "low":
      return "info";
    default:
      return "muted";
  }
}

function SignalTimeline({ signals }: { signals: AccountSignal[] }) {
  if (!signals || signals.length === 0) {
    return (
      <p className="px-1 py-8 text-center text-sm text-muted-foreground">
        No signals recorded for this account yet.
      </p>
    );
  }
  return (
    <ol className="relative space-y-0">
      {signals.map((sig, i) => {
        const ts = sig.ts ?? sig.timestamp;
        const title = sig.label ?? sig.type ?? "Signal";
        const body = sig.content ?? sig.summary;
        const isLast = i === signals.length - 1;
        return (
          <li key={i} className="relative flex gap-3 pb-5">
            {!isLast && (
              <span
                aria-hidden
                className="absolute left-[5px] top-4 h-full w-px bg-border"
              />
            )}
            <span className="relative z-10 mt-1 h-[11px] w-[11px] shrink-0 rounded-full bg-primary ring-4 ring-primary/15" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium capitalize">
                  {title.replace(/_/g, " ")}
                </span>
                {sig.severity && (
                  <Badge variant={severityVariant(sig.severity)}>
                    {String(sig.severity)}
                  </Badge>
                )}
                {sig.source && (
                  <span className="text-[11px] text-muted-foreground">
                    {sig.source}
                  </span>
                )}
              </div>
              {body && (
                <p className="mt-0.5 text-sm text-muted-foreground">{body}</p>
              )}
              {ts && (
                <span className="mt-0.5 block text-[11px] tabular text-muted-foreground/70">
                  {fmtDate(ts)}
                </span>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function HistoryList({ history }: { history: Recommendation[] }) {
  if (!history || history.length === 0) {
    return (
      <p className="px-1 py-8 text-center text-sm text-muted-foreground">
        No prior recommendations. This account has a clean slate.
      </p>
    );
  }
  const statusVariant = (s: string) =>
    s === "approved"
      ? "success"
      : s === "rejected"
        ? "danger"
        : s === "edited"
          ? "info"
          : "muted";
  return (
    <ul className="space-y-3">
      {history.map((rec) => (
        <li
          key={rec.id}
          className="rounded-lg border border-border bg-card p-4"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium">{rec.action.title}</div>
              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                {rec.rationale}
              </p>
            </div>
            <Badge variant={statusVariant(rec.status)}>{rec.status}</Badge>
          </div>
          <div className="mt-2 flex items-center gap-3 text-[11px] tabular text-muted-foreground">
            <span>{fmtDate(rec.created_at)}</span>
            <span>·</span>
            <span>
              confidence {Math.round((rec.confidence?.score ?? 0) * 100)}%
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function ProfileStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Building2;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0">
        <div className="text-[11px] text-muted-foreground">{label}</div>
        <div className="truncate text-sm font-medium">{value}</div>
      </div>
    </div>
  );
}

export default function AccountDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";
  const [detail, setDetail] = useState<AccountDetail | null>(null);
  const [error, setError] = useState(false);
  const [nonce, setNonce] = useState(0);

  const retry = useCallback(() => {
    setError(false);
    setDetail(null);
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!id) return;
    const ctrl = new AbortController();
    void getAccount(id, ctrl.signal)
      .then(setDetail)
      .catch((err) => {
        if (err?.name !== "AbortError") setError(true);
      });
    return () => ctrl.abort();
  }, [id, nonce]);

  if (error) {
    return (
      <div className="mx-auto w-full max-w-5xl px-6 py-8">
        <Link
          href="/inbox"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to inbox
        </Link>
        <div className="panel mt-4">
          <ErrorState
            title="Could not load this account"
            description="The account 360 is temporarily unavailable. Retry, or head back to the inbox."
            onRetry={retry}
          />
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="mx-auto w-full max-w-5xl px-6 py-8">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="mt-3 h-9 w-64" />
        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
          <Skeleton className="h-72 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  const p = detail.profile;
  const health = p.health_score ?? 0;
  const runHref = `/run?${new URLSearchParams({
    account_id: p.account_id,
    domain: p.domain ?? "customer_success",
    signal: detail.signals[0]?.content ?? p.name ?? "",
  }).toString()}`;

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-8">
      <Link
        href="/inbox"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to inbox
      </Link>

      <header className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span
            className={cn(
              "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-base font-semibold tabular text-white",
              healthTone(health),
            )}
          >
            {health}
          </span>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {p.name ?? p.account_id}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {p.risk_level && (
                <Badge variant={riskVariant(p.risk_level)}>
                  {String(p.risk_level)} risk
                </Badge>
              )}
              <span className="text-xs text-muted-foreground">
                {p.domain ?? "customer_success"} · {p.account_id}
              </span>
            </div>
          </div>
        </div>
        <Button asChild size="lg">
          <Link href={runHref}>
            <Play className="h-4 w-4" />
            Run NBA
          </Link>
        </Button>
      </header>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.5fr]">
        <aside className="space-y-5">
          <div className="panel p-5">
            <h2 className="text-eyebrow">Profile</h2>
            <div className="mt-4 grid grid-cols-1 gap-4">
              <ProfileStat
                icon={Sparkles}
                label="ARR"
                value={p.arr != null ? formatArr(p.arr) : "Unknown"}
              />
              <ProfileStat
                icon={Building2}
                label="Segment"
                value={(p.segment as string) ?? "Enterprise"}
              />
              <ProfileStat
                icon={CircleUser}
                label="Owner"
                value={(p.owner as string) ?? "Unassigned"}
              />
              <ProfileStat
                icon={CalendarClock}
                label="Renewal"
                value={fmtDate(p.renewal_date as string) || "Not set"}
              />
            </div>
            <Separator className="my-4" />
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Health score</span>
              <span className="font-medium tabular">{health}/100</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={cn("h-full rounded-full", healthTone(health))}
                style={{ width: `${Math.max(0, Math.min(100, health))}%` }}
              />
            </div>
          </div>

          {detail.current && (
            <div className="panel border-primary/30 p-5">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold">Open recommendation</h2>
              </div>
              <p className="mt-2 text-sm font-medium">
                {detail.current.action.title}
              </p>
              <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">
                {detail.current.rationale}
              </p>
              <Button asChild variant="outline" size="sm" className="mt-3 w-full">
                <Link href={runHref}>Review and decide</Link>
              </Button>
            </div>
          )}
        </aside>

        <section className="panel p-5">
          <Tabs defaultValue="signals">
            <TabsList>
              <TabsTrigger value="signals">
                Signals
                <span className="ml-1.5 tabular opacity-70">
                  {detail.signals.length}
                </span>
              </TabsTrigger>
              <TabsTrigger value="history">
                History
                <span className="ml-1.5 tabular opacity-70">
                  {detail.history.length}
                </span>
              </TabsTrigger>
            </TabsList>
            <TabsContent value="signals" className="pt-2">
              <SignalTimeline signals={detail.signals} />
            </TabsContent>
            <TabsContent value="history" className="pt-2">
              <HistoryList history={detail.history} />
            </TabsContent>
          </Tabs>
        </section>
      </div>
    </div>
  );
}
