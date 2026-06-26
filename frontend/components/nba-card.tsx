"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type {
  HitlDecision,
  Recommendation,
  RecommendationAction,
} from "@/lib/useAgentStream";

function ConfidenceDial({
  score,
  label,
  method,
}: {
  score: number;
  label: string;
  method: string;
}) {
  const clamped = Math.max(0, Math.min(1, score));
  const pct = Math.round(clamped * 100);
  const radius = 26;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * clamped;
  const tone =
    clamped >= 0.75
      ? "text-emerald-500"
      : clamped >= 0.5
        ? "text-amber-500"
        : "text-rose-500";

  return (
    <div className="flex items-center gap-3">
      <div className="relative h-16 w-16 shrink-0">
        <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90">
          <circle
            cx="32"
            cy="32"
            r={radius}
            fill="none"
            strokeWidth="6"
            className="stroke-muted"
          />
          <circle
            cx="32"
            cy="32"
            r={radius}
            fill="none"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
            className={cn("transition-all duration-500", tone)}
            stroke="currentColor"
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-sm font-semibold tabular-nums">
          {pct}
          <span className="text-[10px] text-muted-foreground">%</span>
        </span>
      </div>
      <div className="min-w-0">
        <div className={cn("text-sm font-semibold capitalize", tone)}>{label}</div>
        <div className="text-xs text-muted-foreground">confidence</div>
        <div className="mt-0.5 truncate text-[10px] text-muted-foreground/70">
          {method}
        </div>
      </div>
    </div>
  );
}

function SignalChips({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "supporting" | "contradicting";
}) {
  if (!items || items.length === 0) return null;
  const styles =
    tone === "supporting"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-500/20"
      : "bg-rose-500/10 text-rose-700 dark:text-rose-400 ring-rose-500/20";
  return (
    <div>
      <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <ul className="flex flex-wrap gap-1.5">
        {items.map((s, i) => (
          <li
            key={`${tone}-${i}`}
            className={cn(
              "rounded-full px-2.5 py-1 text-xs ring-1 ring-inset",
              styles,
            )}
          >
            {s}
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface NbaCardProps {
  recommendation: Recommendation | null;
  hitlRequired: boolean;
  onDecision: (
    decision: HitlDecision,
    editedAction: RecommendationAction | null,
    reason: string | null,
  ) => void;
  className?: string;
}

export function NbaCard({
  recommendation,
  hitlRequired,
  onDecision,
  className,
}: NbaCardProps) {
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [reason, setReason] = useState("");

  if (!recommendation) {
    return (
      <Card className={cn("h-full", className)}>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Next best action</CardTitle>
          <CardDescription>
            The recommendation appears here once the agent finishes reasoning.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
            No recommendation yet
          </div>
        </CardContent>
      </Card>
    );
  }

  const rec = recommendation;
  const decided = rec.status !== "proposed";
  const isOpportunity = rec.risk_opportunity?.type === "opportunity";

  const beginEdit = () => {
    setEditTitle(rec.action.title);
    setEditDescription(rec.action.description);
    setEditing(true);
  };

  const submitEdit = () => {
    onDecision(
      "edit",
      {
        key: rec.action.key,
        title: editTitle.trim() || rec.action.title,
        description: editDescription.trim() || rec.action.description,
      },
      reason.trim() || null,
    );
    setEditing(false);
  };

  const statusStyles: Record<string, string> = {
    proposed: "bg-sky-500/10 text-sky-600 dark:text-sky-400 ring-sky-500/20",
    approved:
      "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20",
    rejected: "bg-rose-500/10 text-rose-600 dark:text-rose-400 ring-rose-500/20",
    edited: "bg-violet-500/10 text-violet-600 dark:text-violet-400 ring-violet-500/20",
  };

  return (
    <Card className={cn("flex h-full flex-col", className)}>
      <CardHeader className="gap-3 pb-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-2">
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset",
                  isOpportunity
                    ? "bg-emerald-500/10 text-emerald-600 ring-emerald-500/20"
                    : "bg-amber-500/10 text-amber-600 ring-amber-500/20",
                )}
              >
                {rec.risk_opportunity?.type ?? "action"}
              </span>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset",
                  statusStyles[rec.status] ?? statusStyles.proposed,
                )}
              >
                {rec.status}
              </span>
            </div>
            <CardTitle className="text-base font-semibold leading-snug">
              {rec.action.title}
            </CardTitle>
            <CardDescription className="mt-1">
              {rec.action.description}
            </CardDescription>
          </div>
          <ConfidenceDial
            score={rec.confidence?.score ?? 0}
            label={rec.confidence?.label ?? "unknown"}
            method={rec.confidence?.method ?? ""}
          />
        </div>
      </CardHeader>

      <CardContent className="flex-1 space-y-5 overflow-y-auto">
        {rec.risk_opportunity?.summary && (
          <div
            className={cn(
              "rounded-lg border-l-2 bg-muted/40 px-3 py-2 text-sm",
              isOpportunity ? "border-l-emerald-500" : "border-l-amber-500",
            )}
          >
            {rec.risk_opportunity.summary}
          </div>
        )}

        <section>
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Rationale
          </h4>
          <p className="text-sm leading-relaxed text-foreground/90">
            {rec.rationale}
          </p>
        </section>

        {rec.evidence && rec.evidence.length > 0 && (
          <section>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Evidence ({rec.evidence.length})
            </h4>
            <ul className="space-y-2">
              {rec.evidence.map((ev, i) => (
                <li
                  key={`${ev.source_id}-${i}`}
                  className="rounded-lg border bg-card px-3 py-2"
                >
                  <p className="text-sm font-medium text-foreground/90">
                    {ev.claim}
                  </p>
                  <blockquote className="mt-1 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                    &ldquo;{ev.snippet}&rdquo;
                  </blockquote>
                  <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground/70">
                    <span className="rounded bg-muted px-1.5 py-0.5 font-mono">
                      {ev.source_type}:{ev.source_id}
                    </span>
                    <span className="tabular-nums">
                      span {ev.span?.start}-{ev.span?.end}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <SignalChips
            title="Supporting"
            items={rec.signals?.supporting ?? []}
            tone="supporting"
          />
          <SignalChips
            title="Contradicting"
            items={rec.signals?.contradicting ?? []}
            tone="contradicting"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          {rec.counterfactual && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Counterfactual
              </h4>
              <p className="text-sm text-foreground/80">{rec.counterfactual}</p>
            </section>
          )}
          {rec.expected_impact && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Expected impact
              </h4>
              <div className="flex items-center gap-2 text-sm">
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
                    rec.expected_impact.direction === "up"
                      ? "bg-emerald-500/10 text-emerald-600 ring-emerald-500/20"
                      : "bg-rose-500/10 text-rose-600 ring-rose-500/20",
                  )}
                >
                  {rec.expected_impact.direction === "up" ? "▲" : "▼"}{" "}
                  {rec.expected_impact.kpi}
                </span>
                <span className="text-foreground/80">
                  {rec.expected_impact.estimate}
                </span>
              </div>
            </section>
          )}
        </div>

        {editing && (
          <section className="space-y-2 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3">
            <h4 className="text-[11px] font-semibold uppercase tracking-wide text-violet-600">
              Edit action
            </h4>
            <input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              placeholder="Action title"
              className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
            <textarea
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              placeholder="Action description"
              rows={3}
              className="w-full resize-none rounded-md border bg-background px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for edit (optional)"
              className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
          </section>
        )}
      </CardContent>

      <CardFooter className="flex-col items-stretch gap-2 border-t pt-4">
        {decided ? (
          <p className="text-center text-sm text-muted-foreground">
            Decision recorded:{" "}
            <span className="font-medium capitalize text-foreground">
              {rec.status}
            </span>
          </p>
        ) : editing ? (
          <div className="flex gap-2">
            <Button className="flex-1" onClick={submitEdit}>
              Save and approve
            </Button>
            <Button
              variant="ghost"
              className="flex-1"
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex gap-2">
            <Button
              className="flex-1"
              disabled={!hitlRequired}
              onClick={() => onDecision("approve", null, null)}
            >
              Approve
            </Button>
            <Button
              variant="outline"
              className="flex-1"
              disabled={!hitlRequired}
              onClick={beginEdit}
            >
              Edit
            </Button>
            <Button
              variant="destructive"
              className="flex-1"
              disabled={!hitlRequired}
              onClick={() => onDecision("reject", null, null)}
            >
              Reject
            </Button>
          </div>
        )}
        {!decided && !hitlRequired && !editing && (
          <p className="text-center text-xs text-muted-foreground">
            Approval unlocks when the agent requests human review.
          </p>
        )}
      </CardFooter>
    </Card>
  );
}

export default NbaCard;
