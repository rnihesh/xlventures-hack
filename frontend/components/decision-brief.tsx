"use client";

// The exportable Decision Brief: the one-pager a CSM hands to leadership.
//
// It renders a stored run's recommendation as a polished, print-friendly
// artifact and lets the user download it as Markdown or send it to the browser
// print dialog (window.print on an isolated layout). The authoritative data is
// the org-scoped GET /runs/{id}/brief projection; when the backend is offline we
// degrade gracefully to a brief built from the in-memory recommendation so the
// demo never blanks out. No re-run and no LLM are ever triggered.

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  Download,
  FileText,
  Loader2,
  Printer,
  ShieldCheck,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getBrief } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Alternative,
  DecisionBriefData,
  Evidence,
  MissingInformation,
  PolicyGate,
} from "@/lib/types";
import type { Recommendation } from "@/lib/useAgentStream";

// ---------------------------------------------------------------------------
// Data shaping
// ---------------------------------------------------------------------------

function read<T>(obj: unknown, key: string): T | undefined {
  return (obj as Record<string, unknown> | null | undefined)?.[key] as
    | T
    | undefined;
}

// Build a brief from the in-memory recommendation. Used as the offline fallback
// when the backend brief endpoint is unreachable; it carries everything the
// stream already delivered except the captured signal text and account name.
function briefFromRecommendation(rec: Recommendation): DecisionBriefData {
  const policy = read<PolicyGate[]>(rec, "policy") ?? null;
  const summary = policy
    ? {
        total: policy.length,
        passed: policy.filter((g) => g.status === "pass").length,
        warned: policy.filter((g) => g.status === "warn").length,
        failed: policy.filter((g) => g.status === "fail").length,
        requires_approval: policy.some(
          (g) => g.requires_approval && g.status !== "pass",
        ),
      }
    : null;

  const decisionMap: Record<string, string> = {
    approved: "approve",
    rejected: "reject",
    edited: "edit",
  };

  return {
    run_id: rec.run_id,
    generated_at: new Date().toISOString(),
    status: rec.status,
    account: {
      account_id: rec.account_id,
      name: rec.account_id,
      domain: rec.domain,
      health_score: null,
      stage: null,
    },
    signal: { type: "", content: "" },
    recommendation: {
      id: rec.id,
      status: rec.status,
      action: rec.action,
      reasoning: rec.rationale,
      risk_opportunity: rec.risk_opportunity ?? null,
      counterfactual: rec.counterfactual ?? null,
    },
    confidence: rec.confidence,
    expected_impact: rec.expected_impact ?? null,
    evidence: rec.evidence ?? [],
    signals: rec.signals ?? { supporting: [], contradicting: [] },
    alternatives: read<Alternative[]>(rec, "alternatives") ?? [],
    policy: policy && summary ? { results: policy, summary } : null,
    missing_information:
      read<MissingInformation[]>(rec, "missing_information") ?? [],
    human_decision:
      rec.status && rec.status !== "proposed"
        ? {
            decision: decisionMap[rec.status] ?? rec.status,
            edited_action: null,
            reason: null,
            recorded_at: null,
          }
        : null,
    outcome: null,
  };
}

function pct(score: number | null | undefined): string {
  if (typeof score !== "number") return "n/a";
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Markdown export
// ---------------------------------------------------------------------------

function briefToMarkdown(b: DecisionBriefData): string {
  const lines: string[] = [];
  const L = (s = "") => lines.push(s);

  L(`# Decision Brief`);
  L();
  L(`**Account:** ${b.account.name} (${b.account.account_id})`);
  L(`**Domain:** ${b.account.domain}`);
  if (typeof b.account.health_score === "number") {
    L(`**Health score:** ${b.account.health_score}`);
  }
  L(`**Generated:** ${fmtDate(b.generated_at)}`);
  L();

  if (b.signal?.content) {
    L(`## Signal / Context`);
    L(`${b.signal.type ? `_${b.signal.type}_ - ` : ""}${b.signal.content}`);
    L();
  }

  L(`## Recommended Next Best Action`);
  L(`**${b.recommendation.action.title}**`);
  if (b.recommendation.action.description) {
    L();
    L(b.recommendation.action.description);
  }
  L();
  L(
    `**Confidence:** ${pct(b.confidence?.score)} (${
      b.confidence?.label ?? "n/a"
    }) - method: ${b.confidence?.method ?? "n/a"}`,
  );
  if (b.expected_impact) {
    L(
      `**Expected impact:** ${b.expected_impact.kpi} ${
        b.expected_impact.direction === "up" ? "up" : "down"
      } ${b.expected_impact.estimate}`,
    );
  }
  if (b.recommendation.risk_opportunity?.summary) {
    L(
      `**${b.recommendation.risk_opportunity.type}:** ${b.recommendation.risk_opportunity.summary}`,
    );
  }
  L();

  if (b.recommendation.reasoning) {
    L(`## Reasoning`);
    L(b.recommendation.reasoning);
    L();
  }

  if (b.evidence.length) {
    L(`## Evidence`);
    b.evidence.forEach((ev: Evidence) => {
      L(`- **${ev.claim}**`);
      L(`  > ${ev.snippet}`);
      L(
        `  Source: ${ev.source_type}:${ev.source_id} (span ${ev.span?.start}-${ev.span?.end})`,
      );
    });
    L();
  }

  if (b.signals?.supporting?.length || b.signals?.contradicting?.length) {
    L(`## Signals`);
    if (b.signals.supporting?.length) {
      L(`**Supporting:** ${b.signals.supporting.join(", ")}`);
    }
    if (b.signals.contradicting?.length) {
      L(`**Contradicting:** ${b.signals.contradicting.join(", ")}`);
    }
    L();
  }

  if (b.alternatives.length) {
    L(`## Considered Alternatives`);
    b.alternatives.forEach((alt: Alternative) => {
      const tag = alt.chosen ? " (chosen)" : "";
      L(`- **${alt.action.title}**${tag} - score ${pct(alt.score)}`);
      if (!alt.chosen && alt.why_not) L(`  Why not: ${alt.why_not}`);
    });
    L();
  }

  if (b.policy) {
    L(`## Policy / Guardrails`);
    L(
      `${b.policy.summary.passed} passed, ${b.policy.summary.warned} warned, ${b.policy.summary.failed} failed of ${b.policy.summary.total}.`,
    );
    b.policy.results.forEach((g: PolicyGate) => {
      L(`- [${g.status.toUpperCase()}] ${g.description}: ${g.detail}`);
    });
    L();
  }

  if (b.missing_information.length) {
    L(`## What We Still Need To Know`);
    b.missing_information.forEach((m: MissingInformation) => {
      L(`- ${m.gap}${m.why_it_matters ? ` - ${m.why_it_matters}` : ""}`);
    });
    L();
  }

  if (b.human_decision?.decision) {
    L(`## Human Decision`);
    L(`**Decision:** ${b.human_decision.decision}`);
    if (b.human_decision.reason) L(`**Reason:** ${b.human_decision.reason}`);
    if (b.human_decision.recorded_at) {
      L(`**Recorded:** ${fmtDate(b.human_decision.recorded_at)}`);
    }
    L();
  }

  if (b.outcome) {
    L(`## Recorded Outcome`);
    L(`**Outcome:** ${b.outcome.decision}`);
    if (b.outcome.reason) L(`**Reason:** ${b.outcome.reason}`);
    const metrics = Object.entries(b.outcome.metrics ?? {});
    if (metrics.length) {
      L(
        `**Metrics:** ${metrics
          .map(([k, v]) => `${k}: ${String(v)}`)
          .join(", ")}`,
      );
    }
    L();
  }

  return lines.join("\n");
}

function downloadMarkdown(b: DecisionBriefData) {
  const md = briefToMarkdown(b);
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `decision-brief-${b.account.account_id}-${b.run_id.slice(
    0,
    8,
  )}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Presentational pieces (shared by screen + print)
// ---------------------------------------------------------------------------

function MetaRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="text-sm font-medium text-foreground">{value}</span>
    </div>
  );
}

function BriefSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-primary">
        {title}
      </h3>
      {children}
    </section>
  );
}

function BriefBody({ brief }: { brief: DecisionBriefData }) {
  const b = brief;
  const statusBadge =
    b.policy?.summary.requires_approval
      ? { label: "Approval required", variant: "danger" as const }
      : b.policy && b.policy.summary.failed > 0
        ? { label: "Guardrail failed", variant: "danger" as const }
        : b.policy && b.policy.summary.warned > 0
          ? { label: "Cleared with warnings", variant: "warning" as const }
          : { label: "Guardrails cleared", variant: "success" as const };

  return (
    <div className="space-y-6">
      {/* Masthead */}
      <header className="space-y-3 border-b border-border pb-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-primary">
            <ShieldCheck className="h-5 w-5" />
            <span className="text-eyebrow text-primary">Decision Brief</span>
          </div>
          <span className="text-xs text-muted-foreground">
            {fmtDate(b.generated_at)}
          </span>
        </div>
        <h2 className="text-xl font-semibold leading-tight text-foreground">
          {b.recommendation.action.title}
        </h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <MetaRow label="Account" value={b.account.name} />
          <MetaRow label="Domain" value={b.account.domain} />
          <MetaRow
            label="Confidence"
            value={`${pct(b.confidence?.score)} ${b.confidence?.label ?? ""}`}
          />
          <MetaRow
            label="Status"
            value={<Badge variant={statusBadge.variant}>{statusBadge.label}</Badge>}
          />
        </div>
      </header>

      {b.signal?.content && (
        <BriefSection title="Signal / Context">
          <p className="text-sm leading-relaxed text-foreground/90">
            {b.signal.type && (
              <span className="mr-2 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                {b.signal.type}
              </span>
            )}
            {b.signal.content}
          </p>
        </BriefSection>
      )}

      <BriefSection title="Recommended next best action">
        {b.recommendation.action.description && (
          <p className="text-sm leading-relaxed text-foreground/90">
            {b.recommendation.action.description}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Badge variant="muted">
            Confidence {pct(b.confidence?.score)} ({b.confidence?.label})
          </Badge>
          <span className="text-[10px] text-muted-foreground/70">
            {b.confidence?.method}
          </span>
          {b.expected_impact && (
            <Badge
              variant={
                b.expected_impact.direction === "up" ? "success" : "danger"
              }
            >
              {b.expected_impact.kpi} {b.expected_impact.estimate}
            </Badge>
          )}
        </div>
        {b.recommendation.risk_opportunity?.summary && (
          <p
            className={cn(
              "rounded-md border-l-2 bg-muted/40 px-3 py-2 text-sm",
              b.recommendation.risk_opportunity.type === "opportunity"
                ? "border-l-primary"
                : "border-l-destructive",
            )}
          >
            {b.recommendation.risk_opportunity.summary}
          </p>
        )}
      </BriefSection>

      {b.recommendation.reasoning && (
        <BriefSection title="Reasoning">
          <p className="text-sm leading-relaxed text-foreground/90">
            {b.recommendation.reasoning}
          </p>
        </BriefSection>
      )}

      {b.evidence.length > 0 && (
        <BriefSection title={`Evidence (${b.evidence.length})`}>
          <ul className="space-y-2">
            {b.evidence.map((ev, i) => (
              <li
                key={`${ev.source_id}-${i}`}
                className="rounded-md border border-border bg-card px-3 py-2"
              >
                <p className="text-sm font-medium text-foreground/90">
                  {ev.claim}
                </p>
                <blockquote className="mt-1 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                  &ldquo;{ev.snippet}&rdquo;
                </blockquote>
                <span className="mt-1.5 inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground/80">
                  {ev.source_type}:{ev.source_id}
                </span>
              </li>
            ))}
          </ul>
        </BriefSection>
      )}

      {(b.signals?.supporting?.length > 0 ||
        b.signals?.contradicting?.length > 0) && (
        <BriefSection title="Signals">
          <div className="grid gap-3 sm:grid-cols-2">
            {b.signals.supporting?.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Supporting
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {b.signals.supporting.map((s, i) => (
                    <Badge key={`sup-${i}`} variant="success">
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {b.signals.contradicting?.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Contradicting
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {b.signals.contradicting.map((s, i) => (
                    <Badge key={`con-${i}`} variant="danger">
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </BriefSection>
      )}

      {b.alternatives.length > 0 && (
        <BriefSection title="Considered alternatives">
          <ul className="space-y-1.5">
            {b.alternatives.map((alt, i) => (
              <li
                key={`${alt.action.key}-${i}`}
                className={cn(
                  "rounded-md border px-3 py-2",
                  alt.chosen
                    ? "border-primary/30 bg-primary/5"
                    : "border-border bg-muted/30",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-foreground/90">
                    {alt.action.title}
                    {alt.chosen && (
                      <Badge variant="success" className="ml-2">
                        chosen
                      </Badge>
                    )}
                  </span>
                  <span className="text-[11px] tabular text-muted-foreground">
                    {pct(alt.score)}
                  </span>
                </div>
                {!alt.chosen && alt.why_not && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    <span className="font-semibold text-foreground/80">
                      Why not:{" "}
                    </span>
                    {alt.why_not}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </BriefSection>
      )}

      {b.policy && (
        <BriefSection title="Policy / guardrails">
          <p className="text-xs text-muted-foreground">
            {b.policy.summary.passed} passed, {b.policy.summary.warned} warned,{" "}
            {b.policy.summary.failed} failed of {b.policy.summary.total}.
          </p>
          <ul className="space-y-1.5">
            {b.policy.results.map((g, i) => (
              <li
                key={`${g.rule_id}-${i}`}
                className="flex items-start gap-2 text-xs"
              >
                <Badge
                  variant={
                    g.status === "pass"
                      ? "success"
                      : g.status === "warn"
                        ? "warning"
                        : "danger"
                  }
                >
                  {g.status}
                </Badge>
                <span className="text-foreground/80">
                  <span className="font-medium">{g.description}:</span>{" "}
                  {g.detail}
                </span>
              </li>
            ))}
          </ul>
        </BriefSection>
      )}

      {b.missing_information.length > 0 && (
        <BriefSection title="What we still need to know">
          <ul className="space-y-1.5">
            {b.missing_information.map((m, i) => (
              <li key={`gap-${i}`} className="text-sm text-foreground/85">
                <span className="font-medium">{m.gap}</span>
                {m.why_it_matters && (
                  <span className="text-muted-foreground"> - {m.why_it_matters}</span>
                )}
              </li>
            ))}
          </ul>
        </BriefSection>
      )}

      {(b.human_decision?.decision || b.outcome) && (
        <BriefSection title="Human decision & outcome">
          <div className="grid gap-3 sm:grid-cols-2">
            {b.human_decision?.decision && (
              <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Decision
                </span>
                <p className="text-sm font-medium capitalize text-foreground">
                  {b.human_decision.decision}
                </p>
                {b.human_decision.reason && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {b.human_decision.reason}
                  </p>
                )}
                {b.human_decision.recorded_at && (
                  <p className="mt-0.5 text-[10px] text-muted-foreground/70">
                    {fmtDate(b.human_decision.recorded_at)}
                  </p>
                )}
              </div>
            )}
            {b.outcome && (
              <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Recorded outcome
                </span>
                <p className="text-sm font-medium capitalize text-foreground">
                  {b.outcome.decision}
                </p>
                {Object.entries(b.outcome.metrics ?? {}).length > 0 && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {Object.entries(b.outcome.metrics)
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join(", ")}
                  </p>
                )}
              </div>
            )}
          </div>
        </BriefSection>
      )}

      <footer className="border-t border-border pt-3 text-[10px] text-muted-foreground/70">
        Run {b.run_id} - generated from stored decision state, no re-run.
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overlay + trigger
// ---------------------------------------------------------------------------

export interface DecisionBriefProps {
  recommendation: Recommendation;
  className?: string;
}

export function DecisionBrief({ recommendation, className }: DecisionBriefProps) {
  const [open, setOpen] = useState(false);
  const [brief, setBrief] = useState<DecisionBriefData | null>(null);
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const load = useCallback(async () => {
    setOpen(true);
    setLoading(true);
    // Prefer the authoritative org-scoped backend projection; degrade to the
    // in-memory recommendation so the demo still exports while offline.
    try {
      const data = await getBrief(recommendation.run_id);
      setBrief(data);
    } catch {
      setBrief(briefFromRecommendation(recommendation));
    } finally {
      setLoading(false);
    }
  }, [recommendation]);

  // Lock background scroll while the overlay is open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const overlay =
    open && mounted
      ? createPortal(
          <div id="decision-brief-portal" className="brief-portal">
            <div
              className="brief-scrim fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
              onClick={() => setOpen(false)}
              aria-hidden
            />
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Decision brief"
              className="brief-sheet fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[min(92vw,820px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl"
            >
              <div className="brief-toolbar flex items-center justify-between gap-2 border-b border-border bg-background/95 px-4 py-3">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <FileText className="h-4 w-4 text-primary" />
                  Decision brief
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!brief}
                    onClick={() => brief && downloadMarkdown(brief)}
                  >
                    <Download className="h-4 w-4" />
                    Markdown
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!brief}
                    onClick={() => window.print()}
                  >
                    <Printer className="h-4 w-4" />
                    Print
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setOpen(false)}
                    aria-label="Close"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="brief-content overflow-y-auto px-6 py-6">
                {loading || !brief ? (
                  <div className="flex h-48 items-center justify-center text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin" />
                  </div>
                ) : (
                  <BriefBody brief={brief} />
                )}
              </div>
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className={className}
        onClick={load}
      >
        <FileText className="h-4 w-4" />
        Export brief
      </Button>
      {overlay}
    </>
  );
}

export default DecisionBrief;
