"use client";

import {
  ArrowRight,
  CheckCircle2,
  XCircle,
  PencilLine,
  TrendingUp,
  Sparkles,
  History,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfidenceDial } from "@/components/confidence-dial";
import { cn } from "@/lib/utils";

export interface LearningEpisode {
  id: string;
  account_id?: string;
  domain: string;
  situation: string;
  action_key: string;
  decision?: string | null;
  reason?: string | null;
  outcome?: {
    note?: string;
    kpi?: string;
    before?: number | string;
    after?: number | string;
  } | null;
  recommendation?: {
    action?: { title?: string; key?: string };
    confidence?: { score?: number };
  } | null;
  created_at?: string;
  improved?: boolean;
}

// One point on the REAL acceptance trend: the cumulative acceptance rate after
// each recorded decision, in chronological order. Comes straight from
// /learning, computed from actual outcomes (never a synthetic curve).
export interface TrendPoint {
  index: number;
  account_id?: string;
  decision?: string;
  accepted?: boolean;
  rate: number;
}

export interface LearningData {
  episodes: LearningEpisode[];
  accepted_rate: number;
  trend?: TrendPoint[];
  decided?: number;
  before_after: {
    kpi: string;
    before: number | string;
    after: number | string;
    note?: string;
    // Projected, not actual. has_data is false until real NRR metrics exist.
    has_data?: boolean;
    projected?: boolean;
  };
}

function decisionMeta(decision?: string | null) {
  const d = (decision || "").toLowerCase();
  if (d.includes("approve") || d.includes("accept"))
    return {
      label: "Accepted",
      icon: CheckCircle2,
      tone: "text-primary",
      chip: "bg-primary/10 text-primary ring-primary/20",
    };
  if (d.includes("reject") || d.includes("dismiss"))
    return {
      label: "Rejected",
      icon: XCircle,
      tone: "text-destructive",
      chip: "bg-destructive/10 text-destructive ring-destructive/20",
    };
  if (d.includes("edit"))
    return {
      label: "Edited",
      icon: PencilLine,
      tone: "text-primary",
      chip: "bg-primary/10 text-primary ring-primary/25",
    };
  return {
    label: "Pending",
    icon: History,
    tone: "text-muted-foreground",
    chip: "bg-muted text-muted-foreground ring-border",
  };
}

function numeric(v: number | string | undefined): number | null {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const m = v.replace(/[^0-9.\-]/g, "");
    const n = parseFloat(m);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function Sparkline({ series }: { series: number[] }) {
  const w = 240;
  const h = 56;
  const max = Math.max(...series);
  const min = Math.min(...series);
  const range = max - min || 1;
  const pts = series.map((v, i) => {
    const x = (i / (series.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 6) - 3;
    return [x, y] as const;
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `0,${h} ${line} ${w},${h}`;
  const last = pts[pts.length - 1];

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="h-14 w-full"
    >
      <defs>
        <linearGradient id="learn-spark" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.28" />
          <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill="url(#learn-spark)" />
      <polyline
        points={line}
        fill="none"
        stroke="hsl(var(--primary))"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={last[0]} cy={last[1]} r="3" fill="hsl(var(--primary))" />
    </svg>
  );
}

export function LearningPanel({ data }: { data: LearningData }) {
  const { episodes, accepted_rate, before_after } = data;
  const before = numeric(before_after.before);
  const after = numeric(before_after.after);
  const nrrHasData = before_after.has_data !== false;
  const hasDelta = nrrHasData && before !== null && after !== null;
  const delta = hasDelta ? after! - before! : null;
  const improved = delta !== null ? delta >= 0 : true;
  // The acceptance trend is the REAL cumulative series from /learning, one
  // point per recorded decision. No synthetic curve.
  const series = (data.trend ?? [])
    .map((p) => p.rate)
    .filter((r) => Number.isFinite(r));
  const decided = data.decided ?? series.length;

  // Surface the most instructive "wrong call that got corrected".
  const learnedFrom =
    episodes.find((e) => {
      const d = (e.decision || "").toLowerCase();
      return d.includes("reject") || d.includes("edit") || e.improved;
    }) || episodes[0];

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Before / After KPI delta */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide">
              <TrendingUp className="h-3.5 w-3.5" />
              Outcome delta
              <span
                className="ml-auto rounded-full bg-secondary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground"
                title="Projection, not an actual. Derived from the outcome simulator across decided episodes, weighted by confidence and the recorded human decision."
              >
                Projected
              </span>
            </CardDescription>
            <CardTitle className="text-base">{before_after.kpi}</CardTitle>
          </CardHeader>
          <CardContent>
            {nrrHasData ? (
              <>
                <div className="flex items-end gap-3">
                  <div className="flex flex-col">
                    <span className="text-xs text-muted-foreground">Before</span>
                    <span className="font-mono text-2xl font-semibold tabular text-muted-foreground">
                      {String(before_after.before)}
                    </span>
                  </div>
                  <ArrowRight className="mb-2 h-5 w-5 text-muted-foreground" />
                  <div className="flex flex-col">
                    <span className="text-xs text-muted-foreground">After</span>
                    <span
                      className={cn(
                        "font-mono text-3xl font-semibold tabular",
                        improved ? "text-primary" : "text-destructive"
                      )}
                    >
                      {String(before_after.after)}
                    </span>
                  </div>
                </div>
                {delta !== null ? (
                  <div
                    className={cn(
                      "mt-3 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
                      improved
                        ? "bg-primary/10 text-primary ring-primary/20"
                        : "bg-destructive/10 text-destructive ring-destructive/20"
                    )}
                  >
                    <TrendingUp className="h-3 w-3" />
                    {improved ? "+" : ""}
                    {delta.toFixed(Math.abs(delta) < 1 ? 2 : 0)} projected
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Projected NRR appears once decided episodes carry a measured
                metric. Run more outcomes to populate it.
              </p>
            )}
            {before_after.note ? (
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                {before_after.note}
              </p>
            ) : null}
          </CardContent>
        </Card>

        {/* Accepted-rate trend */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <div className="flex items-start justify-between">
              <div>
                <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide">
                  <Sparkles className="h-3.5 w-3.5" />
                  Acceptance rate, trending
                </CardDescription>
                <CardTitle className="text-base">
                  Recommendations the team acts on
                </CardTitle>
              </div>
              <ConfidenceDial
                value={accepted_rate}
                size={72}
                thickness={7}
                sublabel="accepted"
              />
            </div>
          </CardHeader>
          <CardContent>
            {series.length >= 2 ? (
              <Sparkline series={series} />
            ) : (
              <div className="flex h-14 items-center text-xs text-muted-foreground">
                Trend appears once at least two decisions are recorded.
              </div>
            )}
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              Cumulative acceptance after each recorded decision (real, not a
              modeled curve). Current acceptance is{" "}
              <span className="font-mono font-medium tabular text-foreground">
                {Math.round(accepted_rate * 100)}%
              </span>{" "}
              across {decided}{" "}
              {decided === 1 ? "decided episode" : "decided episodes"}.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Spotlight: a past wrong call that improved */}
      {learnedFrom ? (
        <Card className="border-primary/30 bg-primary/[0.03]">
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-primary">
              <History className="h-3.5 w-3.5" />
              What changed since last time
            </CardDescription>
            <CardTitle className="text-base">
              A corrected call, remembered per account
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-muted-foreground">{learnedFrom.situation}</p>
            <div className="flex flex-col gap-2 rounded-lg border border-border bg-background/60 p-3 sm:flex-row sm:items-center">
              <div className="flex-1">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Then
                </span>
                <p className="font-medium">
                  {learnedFrom.recommendation?.action?.title ||
                    learnedFrom.action_key}
                </p>
                <span className="text-xs text-destructive">
                  {decisionMeta(learnedFrom.decision).label}
                  {learnedFrom.reason ? ` -> ${learnedFrom.reason}` : ""}
                </span>
              </div>
              <ArrowRight className="hidden h-5 w-5 shrink-0 text-primary sm:block" />
              <div className="flex-1">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Now
                </span>
                <p className="font-medium text-primary">
                  Reweighted toward the preferred play
                </p>
                <span className="text-xs text-muted-foreground">
                  {learnedFrom.outcome?.note ||
                    "Future runs on this account favor the accepted action."}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Episode log */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Episode memory</CardTitle>
          <CardDescription>
            Every recommendation and its recorded outcome, per account.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {episodes.length === 0 ? (
            <p className="px-6 py-8 text-center text-sm text-muted-foreground">
              No episodes recorded yet. Approve or reject a recommendation to
              start the learning loop.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {episodes.map((ep) => {
                const meta = decisionMeta(ep.decision);
                const Icon = meta.icon;
                const conf = ep.recommendation?.confidence?.score;
                return (
                  <li
                    key={ep.id}
                    className="flex items-start gap-3 px-6 py-4"
                  >
                    <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", meta.tone)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">
                          {ep.recommendation?.action?.title || ep.action_key}
                        </span>
                        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
                          {ep.domain}
                        </span>
                        {ep.account_id ? (
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {ep.account_id}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {ep.situation}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset",
                          meta.chip
                        )}
                      >
                        {meta.label}
                      </span>
                      {typeof conf === "number" ? (
                        <span className="text-[10px] tabular-nums text-muted-foreground">
                          conf {Math.round(conf * 100)}%
                        </span>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default LearningPanel;
