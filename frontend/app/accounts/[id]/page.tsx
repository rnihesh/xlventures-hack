"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  Building2,
  CalendarClock,
  ChevronRight,
  CircleUser,
  FileText,
  FlaskConical,
  GitBranch,
  History,
  Info,
  Layers,
  Minus,
  Play,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ErrorState } from "@/components/ui/states";
import {
  riskVariant,
  formatArr,
  healthTone,
  healthLabel,
  riskMeaning,
} from "@/components/account-table";
import { WhatIfPanel } from "@/components/whatif-panel";
import { AccountTimelineSection } from "@/components/account-timeline";
import { cn } from "@/lib/utils";
import { signalInfo, SIGNAL_SECTION_HELP } from "@/lib/signal-info";
import { getAccount } from "@/lib/api";
import type {
  AccountDetail,
  AccountDocument,
  AccountSignal,
  Evidence,
  Recommendation,
} from "@/lib/types";

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

function severityWord(sev?: string): string {
  switch (String(sev).toLowerCase()) {
    case "high":
      return "Important";
    case "medium":
      return "Worth a look";
    case "low":
      return "Routine";
    default:
      return "Signal";
  }
}

function ToneIcon({ tone }: { tone: "positive" | "negative" | "neutral" }) {
  if (tone === "positive")
    return <TrendingUp className="h-3.5 w-3.5 text-primary" aria-hidden />;
  if (tone === "negative")
    return <TrendingDown className="h-3.5 w-3.5 text-destructive" aria-hidden />;
  return <Minus className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />;
}

function SectionHeader({
  title,
  hint,
  count,
}: {
  title: string;
  hint: string;
  count?: number;
}) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {count != null && (
          <span className="rounded-full bg-secondary px-2 py-0.5 text-xs tabular text-muted-foreground">
            {count}
          </span>
        )}
      </div>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{hint}</p>
    </div>
  );
}

// One signal, rendered with the raw event AND a plain-language explanation
// (what it means + why it matters) so a non-expert never has to decode jargon.
function SignalCard({ signal }: { signal: AccountSignal }) {
  const ts = signal.ts ?? signal.timestamp;
  const title = signal.label ?? signal.type ?? "Signal";
  const body = signal.content ?? signal.summary;
  const info = signalInfo(`${title} ${body ?? ""}`);
  const accent =
    info.tone === "negative"
      ? "border-l-destructive/50"
      : info.tone === "positive"
        ? "border-l-primary/50"
        : "border-l-border";

  return (
    <li className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium capitalize">
          {title.replace(/_/g, " ")}
        </span>
        {signal.severity && (
          <Badge variant={severityVariant(signal.severity)}>
            {severityWord(signal.severity)}
          </Badge>
        )}
        {signal.source && (
          <span className="text-[11px] text-muted-foreground">
            from {signal.source}
          </span>
        )}
        {ts && (
          <span className="ml-auto text-[11px] tabular text-muted-foreground/70">
            {fmtDate(ts)}
          </span>
        )}
      </div>

      {body && <p className="mt-1.5 text-sm text-muted-foreground">{body}</p>}

      <div
        className={cn(
          "mt-3 space-y-2 rounded-md border-l-2 bg-secondary/40 px-3 py-2.5",
          accent,
        )}
      >
        <div className="flex items-start gap-2">
          <ToneIcon tone={info.tone} />
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              What this means
            </div>
            <p className="text-sm text-foreground">{info.meaning}</p>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <Info className="mt-0.5 h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Why it matters
            </div>
            <p className="text-sm text-foreground">{info.whyItMatters}</p>
          </div>
        </div>
      </div>
    </li>
  );
}

function SignalsSection({ signals }: { signals: AccountSignal[] }) {
  return (
    <section className="panel p-5">
      <SectionHeader
        title="Signals we are tracking"
        hint={SIGNAL_SECTION_HELP.signals}
        count={signals.length}
      />
      {signals.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No signals recorded for this account yet.
        </p>
      ) : (
        <ul className="space-y-3">
          {signals.map((sig, i) => (
            <SignalCard key={i} signal={sig} />
          ))}
        </ul>
      )}
    </section>
  );
}

// Collect the evidence the agent cited across the open and past recommendations,
// de-duplicated by source so the documents list reads cleanly.
function collectEvidence(detail: AccountDetail): Evidence[] {
  const recs: (Recommendation | null)[] = [detail.current, ...detail.history];
  const seen = new Set<string>();
  const out: Evidence[] = [];
  for (const rec of recs) {
    if (!rec?.evidence) continue;
    for (const ev of rec.evidence) {
      const key = `${ev.source_id}:${ev.claim}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(ev);
    }
  }
  return out;
}

function prettySourceType(t?: string): string {
  if (!t) return "Document";
  return t
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// A source document the org actually has on this account: an uploaded or pasted
// interaction (crm-notes, transcript, email) or, for the Demo org, a seed doc.
function DocumentRow({ doc }: { doc: AccountDocument }) {
  return (
    <li className="flex gap-3 rounded-lg border border-border bg-card p-4">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
        <FileText className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">
          {doc.title ?? "Interaction"}
        </p>
        {doc.excerpt && (
          <p className="mt-1 whitespace-pre-wrap border-l-2 border-border pl-2.5 text-xs italic text-muted-foreground">
            {doc.excerpt}
          </p>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <Badge variant="muted">{prettySourceType(doc.source_type)}</Badge>
          {doc.ts && <span className="tabular">{fmtDate(doc.ts)}</span>}
        </div>
      </div>
    </li>
  );
}

function DocumentsSection({
  documents,
  evidence,
}: {
  documents: AccountDocument[];
  evidence: Evidence[];
}) {
  const total = documents.length + evidence.length;
  return (
    <section className="panel p-5">
      <SectionHeader
        title="Documents and evidence"
        hint={SIGNAL_SECTION_HELP.documents}
        count={total}
      />
      {total === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No source documents have been linked to this account yet.
        </p>
      ) : (
        <ul className="space-y-3">
          {documents.map((doc) => (
            <DocumentRow key={doc.id} doc={doc} />
          ))}
          {evidence.map((ev, i) => (
            <li
              key={`ev-${i}`}
              className="flex gap-3 rounded-lg border border-border bg-card p-4"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
                <FileText className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">
                  {ev.claim}
                </p>
                {ev.snippet && (
                  <p className="mt-1 border-l-2 border-border pl-2.5 text-xs italic text-muted-foreground">
                    {ev.snippet}
                  </p>
                )}
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                  <Badge variant="muted">{prettySourceType(ev.source_type)}</Badge>
                  <span className="tabular">{ev.source_id}</span>
                  {ev.score != null && (
                    <span>· {Math.round(ev.score * 100)}% relevance</span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function statusLabel(s: string): string {
  switch (s) {
    case "approved":
      return "Approved and sent";
    case "rejected":
      return "Declined";
    case "edited":
      return "Edited then sent";
    case "proposed":
      return "Awaiting decision";
    default:
      return s;
  }
}

function statusVariant(
  s: string,
): "success" | "danger" | "info" | "muted" {
  switch (s) {
    case "approved":
      return "success";
    case "rejected":
      return "danger";
    case "edited":
      return "info";
    default:
      return "muted";
  }
}

function HistorySection({ history }: { history: Recommendation[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="panel p-5">
      <SectionHeader
        title="Past recommendations and outcomes"
        hint={SIGNAL_SECTION_HELP.history}
        count={history.length}
      />
      {history.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No prior recommendations. This account has a clean slate.
        </p>
      ) : (
        <ul className="space-y-3">
          {history.map((rec, idx) => {
            const isOpen = open === idx;
            const pct = Math.round((rec.confidence?.score ?? 0) * 100);
            return (
              <li
                key={rec.id ?? `rec-${idx}`}
                className="overflow-hidden rounded-lg border border-border bg-card"
              >
                <button
                  type="button"
                  onClick={() => setOpen(isOpen ? null : idx)}
                  aria-expanded={isOpen}
                  className="flex w-full items-start justify-between gap-3 p-4 text-left transition-colors hover:bg-accent/40"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                      <ChevronRight
                        className={cn(
                          "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                          isOpen && "rotate-90",
                        )}
                      />
                      {rec.action.title}
                    </div>
                    <p
                      className={cn(
                        "mt-1 text-xs text-muted-foreground",
                        !isOpen && "line-clamp-2",
                      )}
                    >
                      {rec.rationale}
                    </p>
                  </div>
                  <Badge variant={statusVariant(rec.status)}>
                    {statusLabel(rec.status)}
                  </Badge>
                </button>

                {isOpen ? (
                  <div className="space-y-2 border-t border-border bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
                    {rec.action.description ? (
                      <div>
                        <span className="font-medium text-foreground">
                          What it is:{" "}
                        </span>
                        {rec.action.description}
                      </div>
                    ) : null}
                    <div>
                      <span className="font-medium text-foreground">
                        Confidence:{" "}
                      </span>
                      {pct}%
                      {rec.confidence?.label ? ` (${rec.confidence.label})` : ""}
                      {rec.confidence?.method ? ` · ${rec.confidence.method}` : ""}
                    </div>
                    {rec.expected_impact ? (
                      <div>
                        <span className="font-medium text-foreground">
                          Expected impact:{" "}
                        </span>
                        {rec.expected_impact.kpi} {rec.expected_impact.estimate}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
                  <span>{fmtDate(rec.created_at)}</span>
                  <span className="tabular">Confidence {pct}%</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
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

// Small count pill shown on a tab trigger when the section has a known count.
function TabCount({ value }: { value: number }) {
  return (
    <span className="ml-1.5 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] tabular text-muted-foreground">
      {value}
    </span>
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
            description="This account is temporarily unavailable. Retry, or head back to the inbox."
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
  const evidence = collectEvidence(detail);
  const docCount = (detail.documents?.length ?? 0) + evidence.length;
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

      {/* Header: who this account is, at a glance. */}
      <header className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span
            className={cn(
              "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-base font-semibold tabular text-white",
              healthTone(health),
            )}
            aria-hidden
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
                  {String(p.risk_level)} churn risk
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
            Run NBA for this account
          </Link>
        </Button>
      </header>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.5fr]">
        <aside className="space-y-5">
          {/* Profile + labeled health meter. */}
          <div className="panel p-5">
            <h2 className="text-eyebrow">Account profile</h2>

            <div className="mt-4">
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-muted-foreground">Health score</span>
                <span className="font-medium tabular">
                  {health}/100 · {healthLabel(health)}
                </span>
              </div>
              <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={cn("h-full rounded-full", healthTone(health))}
                  style={{ width: `${Math.max(0, Math.min(100, health))}%` }}
                />
              </div>
              {p.risk_level && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {riskMeaning(p.risk_level)}
                </p>
              )}
            </div>

            <Separator className="my-4" />

            <div className="grid grid-cols-1 gap-4">
              <ProfileStat
                icon={Sparkles}
                label="Annual recurring revenue"
                value={p.arr != null ? formatArr(p.arr) : "Unknown"}
              />
              <ProfileStat
                icon={CircleUser}
                label="Account owner"
                value={(p.owner as string) ?? "Unassigned"}
              />
              <ProfileStat
                icon={CalendarClock}
                label="Renewal date"
                value={fmtDate(p.renewal_date as string) || "Not set"}
              />
              <ProfileStat
                icon={Building2}
                label="Segment"
                value={(p.segment as string) ?? "Enterprise"}
              />
              {p.plan && (
                <ProfileStat
                  icon={Layers}
                  label="Plan"
                  value={String(p.plan)}
                />
              )}
              {p.seats != null && (
                <ProfileStat
                  icon={Users}
                  label="Seats"
                  value={String(p.seats)}
                />
              )}
            </div>
          </div>

          {/* The current open recommendation, framed as the next action. */}
          {detail.current && (
            <div className="panel border-primary/30 p-5">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold">
                  Recommended next action
                </h2>
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

        {/* Right side: every detail view is a tab so the page stays scannable.
            The account profile (left) stays visible across all tabs. */}
        <div className="min-w-0">
          <Tabs defaultValue="signals">
            <TabsList className="h-auto flex-wrap justify-start">
              <TabsTrigger value="signals">
                <Activity className="mr-1.5 h-4 w-4" aria-hidden />
                Signals
                <TabCount value={detail.signals.length} />
              </TabsTrigger>
              <TabsTrigger value="documents">
                <FileText className="mr-1.5 h-4 w-4" aria-hidden />
                Documents &amp; context
                <TabCount value={docCount} />
              </TabsTrigger>
              <TabsTrigger value="history">
                <History className="mr-1.5 h-4 w-4" aria-hidden />
                Past runs
                <TabCount value={detail.history.length} />
              </TabsTrigger>
              <TabsTrigger value="timeline">
                <GitBranch className="mr-1.5 h-4 w-4" aria-hidden />
                Timeline
              </TabsTrigger>
              <TabsTrigger value="whatif">
                <FlaskConical className="mr-1.5 h-4 w-4" aria-hidden />
                What-if
              </TabsTrigger>
            </TabsList>

            <TabsContent value="signals">
              <SignalsSection signals={detail.signals} />
            </TabsContent>

            <TabsContent value="documents">
              <DocumentsSection
                documents={detail.documents ?? []}
                evidence={evidence}
              />
            </TabsContent>

            <TabsContent value="history">
              <HistorySection history={detail.history} />
            </TabsContent>

            {/* Audit trail: the full workflow + memory loop for this account.
                Use the route id (stable from first paint) so we never fetch a
                placeholder id. */}
            <TabsContent value="timeline">
              <AccountTimelineSection accountId={id || p.account_id} />
            </TabsContent>

            {/* What-if simulator, clearly framed so it is not mysterious. */}
            <TabsContent value="whatif">
              <div className="mb-3">
                <h2 className="text-lg font-semibold tracking-tight">
                  Try a different scenario
                </h2>
                <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                  Adjust the inputs below (usage, NPS, contract size) to preview
                  how the recommended action and its confidence would change.
                  Nothing here is saved or sent: it is a sandbox for exploring
                  options.
                </p>
              </div>
              <WhatIfPanel
                domain={p.domain ?? "customer_success"}
                accountId={p.account_id}
                baseline={detail.current}
              />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
