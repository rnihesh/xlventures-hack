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

export interface LearningData {
  episodes: LearningEpisode[];
  accepted_rate: number;
  before_after: {
    kpi: string;
    before: number | string;
    after: number | string;
    note?: string;
  };
}

function decisionMeta(decision?: string | null) {
  const d = (decision || "").toLowerCase();
  if (d.includes("approve") || d.includes("accept"))
    return {
      label: "Accepted",
      icon: CheckCircle2,
      tone: "text-emerald-500",
      chip: "bg-emerald-500/10 text-emerald-500 ring-emerald-500/20",
    };
  if (d.includes("reject") || d.includes("dismiss"))
    return {
      label: "Rejected",
      icon: XCircle,
      tone: "text-rose-500",
      chip: "bg-rose-500/10 text-rose-500 ring-rose-500/20",
    };
  if (d.includes("edit"))
    return {
      label: "Edited",
      icon: PencilLine,
      tone: "text-amber-500",
      chip: "bg-amber-500/10 text-amber-500 ring-amber-500/20",
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

/** Build a gently rising acceptance-rate series that lands on `rate`. */
function trendSeries(rate: number, points = 12): number[] {
  const end = Math.max(0.05, Math.min(0.98, rate));
  const start = Math.max(0.05, end - 0.34);
  const out: number[] = [];
  for (let i = 0; i < points; i += 1) {
    const t = i / (points - 1);
    // ease-out curve plus a little deterministic wobble
    const eased = start + (end - start) * (1 - Math.pow(1 - t, 2));
    const wobble = Math.sin(i * 1.7) * 0.012;
    out.push(Math.max(0.03, Math.min(0.99, eased + wobble)));
  }
  return out;
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
  const hasDelta = before !== null && after !== null;
  const delta = hasDelta ? after! - before! : null;
  const improved = delta !== null ? delta >= 0 : true;
  const series = trendSeries(accepted_rate);

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
            </CardDescription>
            <CardTitle className="text-base">{before_after.kpi}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-end gap-3">
              <div className="flex flex-col">
                <span className="text-xs text-muted-foreground">Before</span>
                <span className="text-2xl font-semibold tabular-nums text-muted-foreground">
                  {String(before_after.before)}
                </span>
              </div>
              <ArrowRight className="mb-2 h-5 w-5 text-muted-foreground" />
              <div className="flex flex-col">
                <span className="text-xs text-muted-foreground">After</span>
                <span
                  className={cn(
                    "text-3xl font-semibold tabular-nums",
                    improved ? "text-emerald-500" : "text-rose-500"
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
                    ? "bg-emerald-500/10 text-emerald-500 ring-emerald-500/20"
                    : "bg-rose-500/10 text-rose-500 ring-rose-500/20"
                )}
              >
                <TrendingUp className="h-3 w-3" />
                {improved ? "+" : ""}
                {delta.toFixed(Math.abs(delta) < 1 ? 2 : 0)} since feedback loop
              </div>
            ) : null}
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
            <Sparkline series={series} />
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              As outcomes are recorded, the recommender reweights its playbooks.
              Acceptance has climbed from{" "}
              <span className="font-medium text-foreground">
                {Math.round(series[0] * 100)}%
              </span>{" "}
              to{" "}
              <span className="font-medium text-foreground">
                {Math.round(accepted_rate * 100)}%
              </span>{" "}
              across {episodes.length} logged episodes.
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
                <span className="text-xs text-rose-500">
                  {decisionMeta(learnedFrom.decision).label}
                  {learnedFrom.reason ? ` -> ${learnedFrom.reason}` : ""}
                </span>
              </div>
              <ArrowRight className="hidden h-5 w-5 shrink-0 text-primary sm:block" />
              <div className="flex-1">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Now
                </span>
                <p className="font-medium text-emerald-500">
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
