"use client";

import { useState } from "react";

import { NbaCard } from "@/components/nba-card";
import { RunTrace } from "@/components/run-trace";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useAgentStream } from "@/lib/useAgentStream";

const STATUS_LABEL: Record<string, string> = {
  idle: "Idle",
  starting: "Starting",
  streaming: "Streaming",
  hitl: "Awaiting approval",
  finished: "Finished",
  error: "Error",
};

const STATUS_TONE: Record<string, string> = {
  idle: "bg-muted text-muted-foreground",
  starting: "bg-sky-500/10 text-sky-600 ring-1 ring-inset ring-sky-500/20",
  streaming:
    "bg-amber-500/10 text-amber-600 ring-1 ring-inset ring-amber-500/20 animate-pulse",
  hitl: "bg-violet-500/10 text-violet-600 ring-1 ring-inset ring-violet-500/20",
  finished:
    "bg-emerald-500/10 text-emerald-600 ring-1 ring-inset ring-emerald-500/20",
  error: "bg-rose-500/10 text-rose-600 ring-1 ring-inset ring-rose-500/20",
};

export default function RunPage() {
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
  const [signalText, setSignalText] = useState(
    "Support tickets up 40% this month and last QBR was skipped.",
  );

  const busy = status === "starting" || status === "streaming";

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    void start({
      domain: domain.trim(),
      account_id: accountId.trim(),
      signal: { type: "freeform", content: signalText.trim() },
    });
  };

  return (
    <main className="mx-auto min-h-screen w-full max-w-7xl px-4 py-6 sm:px-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">
            Next Best Action
          </h1>
          <p className="text-sm text-muted-foreground">
            Signal in, explainable and confidence scored action out, gated by you.
          </p>
        </div>
        <span
          className={cn(
            "rounded-full px-3 py-1 text-xs font-medium",
            STATUS_TONE[status] ?? STATUS_TONE.idle,
          )}
        >
          {STATUS_LABEL[status] ?? status}
        </span>
      </header>

      <Card className="mb-6">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold">New run</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={onSubmit}
            className="grid gap-3 md:grid-cols-[180px_180px_1fr_auto] md:items-end"
          >
            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              Domain
              <input
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                className="rounded-md border bg-background px-2.5 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              Account ID
              <input
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                className="rounded-md border bg-background px-2.5 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              Signal
              <input
                value={signalText}
                onChange={(e) => setSignalText(e.target.value)}
                placeholder="Describe the signal to triage"
                className="rounded-md border bg-background px-2.5 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
            <div className="flex gap-2">
              <Button type="submit" disabled={busy || !signalText.trim()}>
                {busy ? "Running" : "Run agent"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={reset}
                disabled={busy || status === "idle"}
              >
                Reset
              </Button>
            </div>
          </form>
          {error && (
            <p className="mt-3 rounded-md bg-rose-500/10 px-3 py-2 text-sm text-rose-600 ring-1 ring-inset ring-rose-500/20">
              {error}
            </p>
          )}
        </CardContent>
      </Card>

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
    </main>
  );
}
