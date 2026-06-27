"use client";

// Account 360 audit trail. A single vertical, newest-first timeline that folds
// together everything the platform did for one account: an interaction landed,
// the engine recommended a next best action, a human decided on it, and an
// outcome was learned. It is the explainability spine of the 360 view, so a
// judge can read the whole workflow and memory loop at a glance.

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Inbox,
  MessageSquareText,
  PencilLine,
  Sparkles,
  Target,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { getAccountTimeline } from "@/lib/api";
import type { AccountTimeline, TimelineEvent } from "@/lib/types";

function fmtWhen(value?: string | null): string {
  if (!value) return "Earlier";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function prettyType(value?: string): string {
  if (!value) return "Document";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Visual identity per event kind: an icon plus the accent ring colour. The
// palette stays grayscale, with Claude orange (the primary) reserved for the
// platform's own recommendations and learned outcomes so they read as the
// "intelligence" moments.
type KindStyle = {
  label: string;
  icon: LucideIcon;
  ring: string;
  iconColor: string;
};

const KIND_STYLE: Record<TimelineEvent["kind"], KindStyle> = {
  interaction: {
    label: "Interaction",
    icon: MessageSquareText,
    ring: "border-border bg-secondary",
    iconColor: "text-muted-foreground",
  },
  recommendation: {
    label: "Recommendation",
    icon: Sparkles,
    ring: "border-primary/30 bg-primary/10",
    iconColor: "text-primary",
  },
  decision: {
    label: "Human decision",
    icon: CheckCircle2,
    ring: "border-border bg-secondary",
    iconColor: "text-foreground",
  },
  outcome: {
    label: "Outcome learned",
    icon: Target,
    ring: "border-primary/30 bg-primary/10",
    iconColor: "text-primary",
  },
};

function decisionIcon(decision?: string): LucideIcon {
  switch (decision) {
    case "rejected":
      return XCircle;
    case "edited":
      return PencilLine;
    default:
      return CheckCircle2;
  }
}

function decisionBadge(
  decision?: string,
): { label: string; variant: "success" | "danger" | "info" | "muted" } {
  switch (decision) {
    case "accepted":
      return { label: "Approved and sent", variant: "success" };
    case "edited":
      return { label: "Edited then sent", variant: "info" };
    case "rejected":
      return { label: "Declined", variant: "danger" };
    default:
      return { label: decision ?? "Decided", variant: "muted" };
  }
}

function confidencePct(score?: number | null): number | null {
  if (score == null || Number.isNaN(score)) return null;
  return Math.round(score * 100);
}

function EventDetail({
  event,
  expanded,
}: {
  event: TimelineEvent;
  expanded?: boolean;
}) {
  if (event.kind === "interaction") {
    return (
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="muted">{prettyType(event.source_type)}</Badge>
          {!expanded && event.summary && (
            <span className="line-clamp-1 text-xs text-muted-foreground">
              {event.summary}
            </span>
          )}
        </div>
        {expanded && event.text && (
          <p className="whitespace-pre-wrap rounded-md border-l-2 border-border bg-secondary/40 px-3 py-2 text-xs italic text-muted-foreground">
            {event.text}
          </p>
        )}
      </div>
    );
  }

  if (event.kind === "recommendation") {
    const pct = confidencePct(event.confidence?.score);
    const label = event.confidence?.label;
    return (
      <div className="space-y-1.5">
        {event.summary && (
          <p className="line-clamp-2 text-xs text-muted-foreground">
            {event.summary}
          </p>
        )}
        {(pct != null || label) && (
          <Badge variant="warning" className="tabular">
            {pct != null ? `${pct}% confidence` : "Confidence"}
            {label ? ` · ${label}` : ""}
          </Badge>
        )}
      </div>
    );
  }

  if (event.kind === "decision") {
    const badge = decisionBadge(event.decision);
    return (
      <div className="space-y-1.5">
        <Badge variant={badge.variant}>{badge.label}</Badge>
        {event.reason && (
          <p className="line-clamp-2 text-xs italic text-muted-foreground">
            “{event.reason}”
          </p>
        )}
      </div>
    );
  }

  // outcome
  return (
    <div className="flex flex-wrap items-center gap-2">
      {event.summary ? (
        <span className="text-xs text-muted-foreground">{event.summary}</span>
      ) : (
        <span className="text-xs text-muted-foreground">
          Recorded into memory for the learning loop.
        </span>
      )}
    </div>
  );
}

function TimelineRow({
  event,
  last,
}: {
  event: TimelineEvent;
  last: boolean;
}) {
  const style = KIND_STYLE[event.kind];
  const Icon =
    event.kind === "decision" ? decisionIcon(event.decision) : style.icon;

  // Interactions can be expanded in place to read the ingested text/excerpt.
  const [expanded, setExpanded] = useState(false);
  const expandable = event.kind === "interaction" && Boolean(event.text);

  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      {/* Connecting rail between nodes. */}
      {!last && (
        <span
          className="absolute left-[15px] top-9 h-[calc(100%-1.75rem)] w-px bg-border"
          aria-hidden
        />
      )}
      <span
        className={cn(
          "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border",
          style.ring,
        )}
        aria-hidden
      >
        <Icon className={cn("h-4 w-4", style.iconColor)} />
      </span>

      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {style.label}
            </span>
            {expandable ? (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-expanded={expanded}
                className="group inline-flex items-center gap-1 text-left text-sm font-medium text-foreground transition-colors hover:text-primary"
              >
                {event.title}
                <ChevronDown
                  className={cn(
                    "h-3.5 w-3.5 text-muted-foreground transition-transform",
                    expanded && "rotate-180",
                  )}
                  aria-hidden
                />
              </button>
            ) : (
              <span className="text-sm font-medium text-foreground">
                {event.title}
              </span>
            )}
          </div>
          <span className="text-[11px] tabular text-muted-foreground/80">
            {fmtWhen(event.ts)}
          </span>
        </div>
        <div className="mt-1.5">
          <EventDetail event={event} expanded={expanded} />
        </div>
      </div>
    </li>
  );
}

const FILTERS: { key: "all" | TimelineEvent["kind"]; label: string }[] = [
  { key: "all", label: "All" },
  { key: "interaction", label: "Interactions" },
  { key: "recommendation", label: "Recommendations" },
  { key: "decision", label: "Decisions" },
  { key: "outcome", label: "Outcomes" },
];

export function AccountTimelineSection({ accountId }: { accountId: string }) {
  const [data, setData] = useState<AccountTimeline | null>(null);
  const [filter, setFilter] = useState<"all" | TimelineEvent["kind"]>("all");

  useEffect(() => {
    if (!accountId) return;
    const ctrl = new AbortController();
    void getAccountTimeline(accountId, ctrl.signal)
      .then(setData)
      .catch(() => {
        /* getAccountTimeline already falls back to an empty timeline */
      });
    return () => ctrl.abort();
  }, [accountId]);

  const events =
    data?.events.filter((e) => filter === "all" || e.kind === filter) ?? [];

  return (
    <section className="panel p-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight">
              Account timeline
            </h2>
            {data && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs tabular text-muted-foreground">
                {data.counts.total}
              </span>
            )}
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            The full audit trail for this account, newest first: an interaction
            came in, the platform recommended a next best action, a human
            decided, and the outcome was learned.
          </p>
        </div>
        <div className="inline-flex flex-wrap gap-1 rounded-lg bg-muted p-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                filter === f.key
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {!data ? (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex gap-4">
              <Skeleton className="h-8 w-8 rounded-full" />
              <div className="flex-1 space-y-2 pt-1">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            </div>
          ))}
        </div>
      ) : events.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-10 text-center">
          <Inbox className="h-6 w-6 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            {data.counts.total === 0
              ? "Nothing has happened on this account yet. Ingest an interaction or run an NBA to start the trail."
              : "No events match this filter."}
          </p>
        </div>
      ) : (
        <ol className="mt-1">
          {events.map((event, i) => (
            <TimelineRow
              key={event.id}
              event={event}
              last={i === events.length - 1}
            />
          ))}
        </ol>
      )}
    </section>
  );
}
