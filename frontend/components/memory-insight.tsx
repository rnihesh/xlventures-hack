"use client";

import { ArrowRight, BrainCircuit, History, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Alternative } from "@/lib/types";

// ---------------------------------------------------------------------------
// "What changed since last time": makes the learning loop visible on the rec
// itself. Two honest sources, in priority order:
//   1. rec.similar_episodes: the prior cited episodes that shifted the ranking
//      (each carries a `what_changed` note from the memory store).
//   2. A shift derived from the alternatives the engine ranked: when memory
//      down-weighted a runner-up, surface "preferred X over Y" from the
//      engine's own why-not reasoning. No numbers are invented here.
// The panel renders nothing when neither source has a learned signal.
// ---------------------------------------------------------------------------

// A prior episode recalled from memory. Shape mirrors the memory store's recall
// dict; every field is optional so the panel renders whatever is present.
export interface SimilarEpisode {
  episode_id?: string;
  account_id?: string;
  domain?: string;
  situation?: string;
  action_key?: string;
  preferred_action_key?: string | null;
  decision?: string;
  similarity?: number;
  phase?: string;
  what_changed?: string | null;
}

// Turn an action key ("schedule_executive_business_review") into a readable
// label ("Schedule executive business review") for episodes that only carry a
// key. Falls back to the raw value when it is not snake_case.
function humanizeKey(key: string | undefined | null): string {
  if (!key) return "an action";
  const words = key.replace(/[_-]+/g, " ").trim();
  if (!words) return "an action";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Classify how learned memory touched a ranked play, read straight from the
// engine's own rationale / why-not strings (see play_recommender). This keeps
// the signal honest: we only claim memory acted when the engine said so.
export type MemorySignal = "favored" | "downweighted" | null;

export function memorySignal(alt: Alternative): MemorySignal {
  const text = `${alt.rationale ?? ""} ${alt.why_not ?? ""}`.toLowerCase();
  if (
    text.includes("rejection") ||
    text.includes("not accepted") ||
    text.includes("down-weight") ||
    text.includes("downweight")
  ) {
    return "downweighted";
  }
  if (text.includes("accepted on similar") || text.includes("favored by learned")) {
    return "favored";
  }
  return null;
}

// Did learned memory measurably move this ranking? True when any candidate was
// favored or penalized by a prior outcome.
export function rankingUsedMemory(alternatives: Alternative[]): boolean {
  return alternatives.some((a) => memorySignal(a) !== null);
}

interface DerivedShift {
  chosenTitle: string;
  overTitle: string;
  reason: string;
}

// Build a "preferred X over Y" story from the ranked alternatives when a
// runner-up was down-weighted by prior outcomes. Returns null when memory did
// not visibly reorder anything.
function deriveShift(alternatives: Alternative[]): DerivedShift | null {
  if (alternatives.length < 2) return null;
  const chosen =
    alternatives.find((a) => a.chosen) ?? alternatives[0];
  const penalized = alternatives.find(
    (a) => a !== chosen && memorySignal(a) === "downweighted",
  );
  if (!chosen || !penalized) return null;
  return {
    chosenTitle: chosen.action.title,
    overTitle: penalized.action.title,
    reason:
      penalized.why_not ??
      "A similar play was not accepted on comparable accounts before.",
  };
}

function decisionVariant(
  decision: string | undefined,
): "success" | "danger" | "muted" {
  const d = (decision ?? "").toLowerCase();
  if (["approve", "approved", "accept", "accepted"].includes(d)) return "success";
  if (["reject", "rejected", "dismiss", "dismissed"].includes(d)) return "danger";
  return "muted";
}

export interface MemoryInsightProps {
  similarEpisodes: SimilarEpisode[];
  alternatives: Alternative[];
  className?: string;
}

export function MemoryInsight({
  similarEpisodes,
  alternatives,
  className,
}: MemoryInsightProps) {
  // Prefer episodes that carry an explicit "what changed" note (same-account
  // precedents). Fall back to any recalled episode, then to the derived shift.
  const cited = similarEpisodes.filter(
    (e) => (e.what_changed && e.what_changed.trim().length > 0) || e.action_key,
  );
  const shift = deriveShift(alternatives);

  if (cited.length === 0 && !shift) return null;

  return (
    <section
      className={cn(
        "rounded-lg border border-primary/25 bg-primary/[0.04]",
        className,
      )}
    >
      <div className="flex items-center gap-1.5 border-b border-primary/15 px-3 py-2">
        <History className="h-3.5 w-3.5 text-primary" />
        <h4 className="text-eyebrow text-primary">What changed since last time</h4>
        <Badge variant="muted" className="ml-auto">
          <Sparkles className="h-3 w-3" />
          learning loop
        </Badge>
      </div>

      <div className="space-y-2.5 px-3 py-3">
        {/* Headline shift, derived from the engine's own ranking reasoning. */}
        {shift && (
          <div className="flex items-start gap-2 rounded-md bg-card px-2.5 py-2 text-sm">
            <BrainCircuit className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <p className="leading-relaxed text-foreground/90">
              Memory shifted this ranking: preferred{" "}
              <span className="font-medium text-foreground">
                {shift.chosenTitle}
              </span>{" "}
              <ArrowRight className="inline h-3 w-3 align-middle text-muted-foreground" />{" "}
              over{" "}
              <span className="font-medium text-foreground">
                {shift.overTitle}
              </span>
              .{" "}
              <span className="text-muted-foreground">{shift.reason}</span>
            </p>
          </div>
        )}

        {/* Prior cited episodes that informed the recommendation. */}
        {cited.length > 0 && (
          <ul className="space-y-2">
            {cited.map((ep, i) => {
              const note =
                ep.what_changed && ep.what_changed.trim().length > 0
                  ? ep.what_changed
                  : `Last time '${humanizeKey(ep.action_key)}' was ${
                      ep.decision ?? "considered"
                    } on a similar account.`;
              return (
                <li
                  key={ep.episode_id ?? `ep-${i}`}
                  className="rounded-md border bg-card px-2.5 py-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-semibold tabular text-muted-foreground">
                      #{i + 1}
                    </span>
                    <Badge variant={decisionVariant(ep.decision)}>
                      {ep.decision ?? "prior"}
                    </Badge>
                    {ep.account_id && (
                      <span className="truncate font-mono text-[10px] text-muted-foreground/70">
                        {ep.account_id}
                      </span>
                    )}
                    {typeof ep.similarity === "number" && (
                      <span className="ml-auto shrink-0 text-[10px] tabular text-muted-foreground">
                        {Math.round(Math.max(0, Math.min(1, ep.similarity)) * 100)}% similar
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-foreground/80">
                    {note}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

export default MemoryInsight;
