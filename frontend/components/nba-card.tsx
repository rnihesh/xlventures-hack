"use client";

import { useState } from "react";
import {
  Check,
  FileText,
  GitBranch,
  HelpCircle,
  Pencil,
  Quote,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alternatives } from "@/components/alternatives";
import { InfoHint } from "@/components/ui/tooltip";
import { toast } from "@/components/ui/toast";
import { explainSignal, SIGNAL_GROUP_HELP } from "@/lib/signal-glossary";
import { cn } from "@/lib/utils";
import type { Alternative, MissingInformation } from "@/lib/types";
import type {
  HitlDecision,
  Recommendation,
  RecommendationAction,
} from "@/lib/useAgentStream";

// The streamed Recommendation may carry an optional `alternatives` array that
// is not part of the frozen useAgentStream type. Read it safely without
// loosening the contract elsewhere.
function readAlternatives(rec: Recommendation): Alternative[] {
  const alts = (rec as unknown as { alternatives?: Alternative[] }).alternatives;
  return Array.isArray(alts) ? alts : [];
}

// The streamed Recommendation may also carry the engine's `missing_information`
// (what we still need to know). Read it safely without loosening the contract.
function readMissingInformation(rec: Recommendation): MissingInformation[] {
  const gaps = (rec as unknown as { missing_information?: MissingInformation[] })
    .missing_information;
  return Array.isArray(gaps) ? gaps : [];
}

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
  // One accent for every confidence level: Claude orange arc on a border track.
  const tone = "text-primary";

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
            className="stroke-border"
          />
          <circle
            cx="32"
            cy="32"
            r={radius}
            fill="none"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
            className={cn("transition-all duration-700 ease-out", tone)}
            stroke="currentColor"
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center font-mono text-sm font-semibold tabular">
          {pct}
          <span className="text-[10px] text-muted-foreground">%</span>
        </span>
      </div>
      <div className="min-w-0">
        <div className={cn("text-sm font-semibold capitalize", tone)}>
          {label}
        </div>
        <div className="text-xs text-muted-foreground">confidence</div>
        <div className="mt-0.5 truncate text-[10px] text-muted-foreground/70">
          {method}
        </div>
      </div>
    </div>
  );
}

function SectionLabel({
  icon: Icon,
  children,
}: {
  icon: typeof FileText;
  children: React.ReactNode;
}) {
  return (
    <h4 className="mb-1.5 flex items-center gap-1.5 text-eyebrow">
      <Icon className="h-3.5 w-3.5" />
      {children}
    </h4>
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
  return (
    <div>
      <h4 className="mb-1.5 flex items-center gap-1 text-eyebrow">
        {title}
        <InfoHint text={SIGNAL_GROUP_HELP[tone]} align="start" />
      </h4>
      <ul className="flex flex-wrap gap-1.5">
        {items.map((s, i) => (
          // Native title gives a quick plain-language read of each cryptic chip.
          <li key={`${tone}-${i}`} title={explainSignal(s)}>
            <Badge variant={tone === "supporting" ? "success" : "danger"}>
              {s}
            </Badge>
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
          <CardTitle className="text-sm font-semibold">
            Next best action
          </CardTitle>
          <CardDescription>
            The recommendation appears here once the agent finishes reasoning.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-muted-foreground">
            <Quote className="h-5 w-5 opacity-50" />
            No recommendation yet
          </div>
        </CardContent>
      </Card>
    );
  }

  const rec = recommendation;
  const decided = rec.status !== "proposed";
  const isOpportunity = rec.risk_opportunity?.type === "opportunity";
  const alternatives = readAlternatives(rec);
  const missingInformation = readMissingInformation(rec);

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
    toast("Edit saved and approved", {
      description: "Your revised action was sent for execution.",
      variant: "success",
    });
  };

  const approve = () => {
    onDecision("approve", null, null);
    toast("Action approved", {
      description: "The recommended play is cleared to execute.",
      variant: "success",
    });
  };

  const reject = () => {
    onDecision("reject", null, null);
    toast("Action rejected", {
      description: "Logged as feedback for the learning loop.",
      variant: "info",
    });
  };

  const statusVariant =
    rec.status === "approved"
      ? "success"
      : rec.status === "rejected"
        ? "danger"
        : rec.status === "edited"
          ? "info"
          : "muted";

  return (
    <Card className={cn("flex animate-rise flex-col", className)}>
      <CardHeader className="gap-3 pb-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-1.5 flex items-center gap-2">
              <Badge variant={isOpportunity ? "success" : "danger"}>
                {rec.risk_opportunity?.type ?? "action"}
              </Badge>
              <Badge variant={statusVariant}>{rec.status}</Badge>
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

      <CardContent className="space-y-5">
        {rec.risk_opportunity?.summary && (
          <div
            className={cn(
              "rounded-lg border-l-2 bg-muted/40 px-3 py-2 text-sm",
              isOpportunity ? "border-l-primary" : "border-l-destructive",
            )}
          >
            {rec.risk_opportunity.summary}
          </div>
        )}

        <section>
          <SectionLabel icon={FileText}>Rationale</SectionLabel>
          <p className="text-sm leading-relaxed text-foreground/90">
            {rec.rationale}
          </p>
        </section>

        {rec.evidence && rec.evidence.length > 0 && (
          <section>
            <SectionLabel icon={Quote}>
              Evidence ({rec.evidence.length})
            </SectionLabel>
            <ul className="space-y-2">
              {rec.evidence.map((ev, i) => (
                <li
                  key={`${ev.source_id}-${i}`}
                  className="rounded-lg border bg-card px-3 py-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-foreground/90">
                      {ev.claim}
                    </p>
                    {typeof ev.score === "number" && (
                      <span className="shrink-0 text-[10px] tabular text-muted-foreground">
                        {Math.round(ev.score * 100)}%
                      </span>
                    )}
                  </div>
                  <blockquote className="mt-1 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                    &ldquo;{ev.snippet}&rdquo;
                  </blockquote>
                  <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground/70">
                    <span className="rounded bg-muted px-1.5 py-0.5 font-mono">
                      {ev.source_type}:{ev.source_id}
                    </span>
                    <span className="tabular">
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

        <Separator />

        <div className="grid gap-4 sm:grid-cols-2">
          {rec.counterfactual && (
            <section>
              <SectionLabel icon={GitBranch}>Counterfactual</SectionLabel>
              <p className="text-sm text-foreground/80">{rec.counterfactual}</p>
            </section>
          )}
          {rec.expected_impact && (
            <section>
              <SectionLabel
                icon={
                  rec.expected_impact.direction === "up"
                    ? TrendingUp
                    : TrendingDown
                }
              >
                Expected impact
              </SectionLabel>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge
                  variant={
                    rec.expected_impact.direction === "up" ? "success" : "danger"
                  }
                >
                  {rec.expected_impact.direction === "up" ? (
                    <TrendingUp className="h-3 w-3" />
                  ) : (
                    <TrendingDown className="h-3 w-3" />
                  )}
                  {rec.expected_impact.kpi}
                </Badge>
                <span className="text-foreground/80">
                  {rec.expected_impact.estimate}
                </span>
              </div>
            </section>
          )}
        </div>

        {alternatives.length > 0 && <Alternatives alternatives={alternatives} />}

        {missingInformation.length > 0 && (
          <section>
            <SectionLabel icon={HelpCircle}>
              What we still need to know
            </SectionLabel>
            <ul className="space-y-2">
              {missingInformation.map((gap, i) => (
                <li
                  key={`gap-${i}`}
                  className="flex gap-2.5 rounded-lg border border-dashed bg-muted/30 px-3 py-2"
                >
                  <span
                    aria-hidden
                    className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground/90">
                      {gap.gap}
                    </p>
                    {gap.why_it_matters && (
                      <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                        {gap.why_it_matters}
                      </p>
                    )}
                    {gap.suggested_source && (
                      <p className="mt-1 text-[10px] text-muted-foreground/70">
                        <span className="text-primary/80">Source:</span>{" "}
                        {gap.suggested_source}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {editing && (
          <section className="space-y-2 rounded-lg border border-primary/30 bg-primary/[0.05] p-3">
            <h4 className="text-eyebrow text-primary">Edit action</h4>
            <Input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              placeholder="Action title"
            />
            <Textarea
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              placeholder="Action description"
              rows={3}
            />
            <Input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for edit (optional)"
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
              <Check className="h-4 w-4" />
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
              onClick={approve}
            >
              <Check className="h-4 w-4" />
              Approve
            </Button>
            <Button
              variant="outline"
              className="flex-1"
              disabled={!hitlRequired}
              onClick={beginEdit}
            >
              <Pencil className="h-4 w-4" />
              Edit
            </Button>
            <Button
              variant="destructive"
              className="flex-1"
              disabled={!hitlRequired}
              onClick={reject}
            >
              <X className="h-4 w-4" />
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
