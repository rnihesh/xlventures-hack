"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  CheckCircle2,
  ListTree,
  Play,
  RotateCcw,
  Sparkles,
  Wrench,
} from "lucide-react";

import { NbaCard } from "@/components/nba-card";
import { PolicyPanel } from "@/components/policy-panel";
import { ExecutePanel } from "@/components/execute-panel";
import { RunTrace } from "@/components/run-trace";
import { ToolCallPanel } from "@/components/tool-call-panel";
import { RecentRuns } from "@/components/recent-runs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { useAgentStream } from "@/lib/useAgentStream";
import { getAccounts, getDomains } from "@/lib/api";
import { getActiveDomain } from "@/lib/active-domain";
import type {
  Account,
  DomainSummary,
  Recommendation as RecommendationContract,
} from "@/lib/types";

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
  starting: "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
  streaming: "bg-primary/12 text-primary ring-1 ring-inset ring-primary/20",
  hitl: "bg-primary/12 text-primary ring-1 ring-inset ring-primary/25",
  finished: "bg-primary/12 text-primary ring-1 ring-inset ring-primary/20",
  error:
    "bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/20",
};

const EXAMPLES = [
  "Support tickets up 40% this month and the last QBR was skipped.",
  "Weekly active users down 18% over the past 30 days.",
  "Champion asked about SSO and 25 more seats for next quarter.",
];

const DEFAULT_DOMAIN = "customer_success";

// Highest risk first so the default account is the one that most needs a play.
const RISK_RANK: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function riskRank(level: string): number {
  return RISK_RANK[level?.toLowerCase()] ?? 2;
}

function sortByRisk(accounts: Account[]): Account[] {
  return [...accounts].sort(
    (a, b) => riskRank(a.risk_level) - riskRank(b.risk_level),
  );
}

function accountLabel(account: Account): string {
  return `${account.name} (${account.account_id}, ${account.risk_level})`;
}

function RunWorkspace() {
  const searchParams = useSearchParams();
  const {
    runId,
    status,
    events,
    recommendation,
    hitlRequired,
    error,
    start,
    submitHitl,
    reset,
  } = useAgentStream();

  const [domain, setDomain] = useState(DEFAULT_DOMAIN);
  const [accountId, setAccountId] = useState("");
  const [signalText, setSignalText] = useState(EXAMPLES[0]);
  const [leftTab, setLeftTab] = useState("trace");

  // Bumps when a run finishes so the Recent runs panel refetches and the
  // just-completed run shows up at the top.
  const [runsRefreshKey, setRunsRefreshKey] = useState(0);

  const [domains, setDomains] = useState<DomainSummary[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  // When the accounts endpoint cannot be reached we fall back to a free-text
  // account input so the form still works offline.
  const [accountsFailed, setAccountsFailed] = useState(false);
  // Honor a deep-linked account_id before account-driven defaults kick in.
  const [pinnedAccountId, setPinnedAccountId] = useState<string | null>(null);
  // A deep-linked signal wins over the first account's last_signal prefill.
  const deepSignalRef = useRef(false);

  // Count tool calls so the tab label reflects live orchestration activity.
  const toolCallCount = events.filter((e) => e.type === "node.started").length;

  // Load the domain list once for the domain dropdown.
  useEffect(() => {
    const controller = new AbortController();
    getDomains(controller.signal)
      .then(setDomains)
      .catch(() => setDomains([]));
    return () => controller.abort();
  }, []);

  // Load accounts whenever the domain changes, then default to the highest-risk
  // account in that domain (unless a deep link pinned a specific account).
  useEffect(() => {
    const controller = new AbortController();
    setAccountsFailed(false);
    getAccounts(controller.signal)
      .then((all) => {
        const scoped = sortByRisk(all.filter((a) => a.domain === domain));
        setAccounts(scoped);
        setAccountId((current) => {
          if (pinnedAccountId && scoped.some((a) => a.account_id === pinnedAccountId)) {
            return pinnedAccountId;
          }
          if (current && scoped.some((a) => a.account_id === current)) {
            return current;
          }
          return scoped[0]?.account_id ?? "";
        });
      })
      .catch(() => {
        setAccounts([]);
        setAccountsFailed(true);
      });
    return () => controller.abort();
  }, [domain, pinnedAccountId]);

  // Default to the active domain pack chosen on the Domains page, unless a deep
  // link explicitly names a domain (that takes precedence).
  useEffect(() => {
    if (searchParams.get("domain")) return;
    setDomain(getActiveDomain());
  }, [searchParams]);

  // Prefill from inbox / account 360 deep links.
  useEffect(() => {
    const a = searchParams.get("account_id");
    const d = searchParams.get("domain");
    const s = searchParams.get("signal");
    if (a) setPinnedAccountId(a);
    if (d) setDomain(d);
    if (s) {
      deepSignalRef.current = true;
      setSignalText(s);
    }
  }, [searchParams]);

  // When the selected account changes, prefill the signal with its last signal.
  // A deep-linked signal takes precedence for the initial selection only.
  const selectedAccount = accounts.find((a) => a.account_id === accountId) ?? null;
  useEffect(() => {
    if (!selectedAccount?.last_signal) return;
    if (deepSignalRef.current) {
      deepSignalRef.current = false;
      return;
    }
    setSignalText(selectedAccount.last_signal);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAccount?.account_id]);

  // When a run reaches a terminal state, refresh the Recent runs list so the
  // newly stored run appears without a manual reload.
  useEffect(() => {
    if (status === "finished") {
      setRunsRefreshKey((k) => k + 1);
    }
  }, [status]);

  const busy = status === "starting" || status === "streaming";
  const idle = status === "idle" && events.length === 0 && !recommendation;

  // The streamed recommendation carries policy gates at runtime; expose it as
  // the shared contract type so the policy and execute panels can read them.
  const contractRecommendation =
    (recommendation as RecommendationContract | null) ?? null;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || !signalText.trim() || !accountId.trim()) return;
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
              <Select
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              >
                {domains.length === 0 && (
                  <option value={domain}>{domain}</option>
                )}
                {domains.map((d) => (
                  <option key={d.key} value={d.key}>
                    {d.display_name}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-eyebrow">Account</span>
              {accountsFailed ? (
                <Input
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                  placeholder="Account ID"
                />
              ) : (
                <Select
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                  disabled={accounts.length === 0}
                >
                  {accounts.length === 0 ? (
                    <option value="">No accounts for this domain</option>
                  ) : (
                    accounts.map((a) => (
                      <option key={a.account_id} value={a.account_id}>
                        {accountLabel(a)}
                      </option>
                    ))
                  )}
                </Select>
              )}
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
                className="rounded-full border border-border bg-card px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <Sparkles className="mr-1 inline h-3 w-3" />
                {ex.length > 36 ? `${ex.slice(0, 36)}...` : ex}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="submit"
              disabled={busy || !signalText.trim() || !accountId.trim()}
            >
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
          <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive ring-1 ring-inset ring-destructive/20">
            {error}
          </p>
        )}
      </div>

      {idle && (
        <div className="panel mb-6 p-6">
          <p className="text-eyebrow">Before you run</p>
          <h2 className="mt-1 text-base font-semibold tracking-tight">
            From a raw signal to an approved play in three steps
          </h2>
          <ol className="mt-4 grid gap-4 sm:grid-cols-3">
            {[
              {
                icon: Sparkles,
                title: "1. Describe the signal",
                desc: "Pick an example above or paste any account signal to triage.",
              },
              {
                icon: ListTree,
                title: "2. Watch it reason",
                desc: "The planner streams an evidence-backed, confidence-scored trace.",
              },
              {
                icon: CheckCircle2,
                title: "3. Approve or edit",
                desc: "Nothing executes until a human approves the play.",
              },
            ].map((step) => {
              const Icon = step.icon;
              return (
                <li
                  key={step.title}
                  className="rounded-xl border border-border bg-card/60 p-4"
                >
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-foreground">
                    <Icon className="h-4 w-4" aria-hidden />
                  </span>
                  <div className="mt-3 text-sm font-medium">{step.title}</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {step.desc}
                  </p>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-6 lg:self-start">
          <Tabs value={leftTab} onValueChange={setLeftTab}>
            <TabsList className="w-full">
              <TabsTrigger value="trace" className="flex-1 gap-1.5">
                <ListTree className="h-3.5 w-3.5" />
                Trace
              </TabsTrigger>
              <TabsTrigger value="tools" className="flex-1 gap-1.5">
                <Wrench className="h-3.5 w-3.5" />
                Tool calls
                {toolCallCount > 0 && (
                  <span className="ml-0.5 rounded-full bg-background/60 px-1.5 text-[10px] tabular">
                    {toolCallCount}
                  </span>
                )}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="trace">
              <RunTrace events={events} />
            </TabsContent>
            <TabsContent value="tools">
              <ToolCallPanel events={events} />
            </TabsContent>
          </Tabs>
        </div>
        <div className="space-y-6">
          <NbaCard
            recommendation={recommendation}
            hitlRequired={hitlRequired}
            onDecision={submitHitl}
          />
          {recommendation && (
            <>
              <PolicyPanel
                gates={contractRecommendation?.policy ?? []}
                domain={domain.trim()}
              />
              <ExecutePanel
                recommendation={contractRecommendation}
                runId={runId}
                accountId={accountId.trim()}
              />
            </>
          )}
        </div>
      </div>

      <section className="mt-6">
        <RecentRuns refreshKey={runsRefreshKey} />
      </section>
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
