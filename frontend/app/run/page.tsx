"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Play, RotateCcw, Sparkles } from "lucide-react";

import { NbaCard } from "@/components/nba-card";
import { RunTrace } from "@/components/run-trace";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useAgentStream } from "@/lib/useAgentStream";

const STATUS_LABEL: Record<string, string> = {
  idle: "Idle",
  starting: "Starting",
  streaming: "Reasoning",
  hitl: "Awaiting approval",
  finished: "Finished",
  error: "Error",
};

const STATUS_TONE: Record<string, string> = {
  idle: "bg-muted text-muted-foreground",
  starting: "bg-sky-500/12 text-sky-600 ring-1 ring-inset ring-sky-500/20",
  streaming:
    "bg-amber-500/12 text-amber-600 ring-1 ring-inset ring-amber-500/20",
  hitl: "bg-violet-500/12 text-violet-600 ring-1 ring-inset ring-violet-500/20",
  finished:
    "bg-emerald-500/12 text-emerald-600 ring-1 ring-inset ring-emerald-500/20",
  error: "bg-rose-500/12 text-rose-600 ring-1 ring-inset ring-rose-500/20",
};

const EXAMPLES = [
  "Support tickets up 40% this month and the last QBR was skipped.",
  "Weekly active users down 18% over the past 30 days.",
  "Champion asked about SSO and 25 more seats for next quarter.",
];

function RunWorkspace() {
  const searchParams = useSearchParams();
  const {
    status,
    events,
    recommendation,
    hitlRequired,
    error,
    start,
    submitHitl,
    reset,
  } = useAgentStream();

  const [domain, setDomain] = useState("customer_success");
  const [accountId, setAccountId] = useState("acct_001");
  const [signalText, setSignalText] = useState(EXAMPLES[0]);

  // Prefill from inbox / account 360 deep links.
  useEffect(() => {
    const a = searchParams.get("account_id");
    const d = searchParams.get("domain");
    const s = searchParams.get("signal");
    if (a) setAccountId(a);
    if (d) setDomain(d);
    if (s) setSignalText(s);
  }, [searchParams]);

  const busy = status === "starting" || status === "streaming";

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || !signalText.trim()) return;
    void start({
      domain: domain.trim(),
      account_id: accountId.trim(),
      signal: { type: "freeform", content: signalText.trim() },
    });
  };

  return (
    <div className="mx-auto w-full max-w-7xl px-6 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-eyebrow">Agent run</div>
          <h1 className="mt-1 text-display">Next Best Action</h1>
          <p className="mt-1.5 max-w-xl text-sm text-muted-foreground">
            Signal in; an explainable, confidence-scored action out, gated by
            your approval.
          </p>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium",
            STATUS_TONE[status] ?? STATUS_TONE.idle,
          )}
        >
          {busy && (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
          )}
          {STATUS_LABEL[status] ?? status}
        </span>
      </header>

      <div className="panel mb-6 p-5">
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-eyebrow">Domain</span>
              <Input
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="customer_success"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-eyebrow">Account ID</span>
              <Input
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                placeholder="acct_001"
              />
            </label>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-eyebrow">Signal</span>
            <Textarea
              value={signalText}
              onChange={(e) => setSignalText(e.target.value)}
              placeholder="Describe the signal to triage"
              rows={2}
            />
          </label>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Examples:</span>
            {EXAMPLES.map((ex, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setSignalText(ex)}
                className="rounded-full border border-border bg-card px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                <Sparkles className="mr-1 inline h-3 w-3" />
                {ex.length > 36 ? `${ex.slice(0, 36)}...` : ex}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button type="submit" disabled={busy || !signalText.trim()}>
              <Play className="h-4 w-4" />
              {busy ? "Running" : "Run agent"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={reset}
              disabled={busy || status === "idle"}
            >
              <RotateCcw className="h-4 w-4" />
              Reset
            </Button>
          </div>
        </form>
        {error && (
          <p className="mt-3 rounded-md bg-rose-500/10 px-3 py-2 text-sm text-rose-600 ring-1 ring-inset ring-rose-500/20">
            {error}
          </p>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-6 lg:self-start">
          <RunTrace events={events} />
        </div>
        <NbaCard
          recommendation={recommendation}
          hitlRequired={hitlRequired}
          onDecision={submitHitl}
        />
      </div>
    </div>
  );
}

export default function RunPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-7xl px-6 py-8">
          <Skeleton className="h-9 w-64" />
          <Skeleton className="mt-6 h-44 w-full rounded-xl" />
        </div>
      }
    >
      <RunWorkspace />
    </Suspense>
  );
}
