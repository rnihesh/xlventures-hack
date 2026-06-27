"use client";

import { useMemo, useState } from "react";
import {
  ChevronDown,
  Layers,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Trophy,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { memorySignal, type MemorySignal } from "@/components/memory-insight";
import { cn } from "@/lib/utils";
import type { Alternative } from "@/lib/types";

function ScoreBar({ score, chosen }: { score: number; chosen: boolean }) {
  const clamped = Math.max(0, Math.min(1, score));
  const pct = Math.round(clamped * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-700 ease-out",
            chosen ? "bg-primary" : "bg-muted-foreground/50",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-8 shrink-0 text-right text-[11px] tabular text-muted-foreground">
        {pct}%
      </span>
    </div>
  );
}

// The engine may attach a memory-free base score per candidate. When present
// for every alternative we can honestly reorder the "without memory" view;
// otherwise we fall back to a labelled lens (no numbers are invented).
function readBaseScore(alt: Alternative): number | null {
  const raw = (alt as unknown as { base_score?: unknown; base_value?: unknown });
  const v = typeof raw.base_score === "number" ? raw.base_score : raw.base_value;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function MemoryTag({ signal }: { signal: MemorySignal }) {
  if (signal === "favored") {
    return (
      <Badge variant="success">
        <ThumbsUp className="h-3 w-3" />
        memory favored
      </Badge>
    );
  }
  if (signal === "downweighted") {
    return (
      <Badge variant="danger">
        <ThumbsDown className="h-3 w-3" />
        memory down-weighted
      </Badge>
    );
  }
  return null;
}

type Mode = "with" | "without";

interface Row {
  alt: Alternative;
  rank: number; // position in the active (mode) ordering
  signal: MemorySignal;
  chosen: boolean;
  score: number; // score shown for the active mode
}

export interface AlternativesProps {
  alternatives: Alternative[];
  className?: string;
}

export function Alternatives({ alternatives, className }: AlternativesProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("with");

  const signals = useMemo(
    () => alternatives.map((a) => memorySignal(a)),
    [alternatives],
  );
  const usedMemory = signals.some((s) => s !== null);

  // Real "without memory" reorder is only honest when every alternative carries
  // a base (memory-free) score. Otherwise the toggle becomes a labelled lens.
  const baseScores = useMemo(
    () => alternatives.map((a) => readBaseScore(a)),
    [alternatives],
  );
  const canReorder = baseScores.length > 0 && baseScores.every((s) => s !== null);

  const withChosenIndex = Math.max(
    0,
    alternatives.findIndex((a) => a.chosen),
  );

  // Build the rows for the active mode. "with" keeps the engine ordering;
  // "without" reorders by base score only when we truly have base scores.
  const rows: Row[] = useMemo(() => {
    if (mode === "without" && canReorder) {
      const order = alternatives
        .map((alt, i) => ({ alt, i, base: baseScores[i] as number }))
        .sort((a, b) => b.base - a.base);
      return order.map((o, rank) => ({
        alt: o.alt,
        rank,
        signal: signals[o.i],
        chosen: rank === 0,
        score: o.base,
      }));
    }
    return alternatives.map((alt, i) => ({
      alt,
      rank: i,
      signal: signals[i],
      chosen: alt.chosen ?? i === 0,
      score: alt.score,
    }));
  }, [mode, canReorder, alternatives, baseScores, signals]);

  if (!alternatives || alternatives.length === 0) return null;

  const count = alternatives.length;
  const panelId = "considered-alternatives";
  const movedCount = signals.filter((s) => s !== null).length;

  // Did disabling memory change the winning play (only knowable when reordered)?
  const chosenChanged =
    mode === "without" &&
    canReorder &&
    rows.length > 0 &&
    rows[0].alt !== alternatives[withChosenIndex];

  return (
    <section className={cn("rounded-lg border bg-card", className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted/50"
      >
        <span className="flex items-center gap-1.5 text-eyebrow">
          <Layers className="h-3.5 w-3.5" />
          Considered {count} {count === 1 ? "action" : "actions"}
          {usedMemory && (
            <Badge variant="muted">
              <Sparkles className="h-3 w-3" />
              memory shaped ranking
            </Badge>
          )}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div id={panelId} className="border-t px-3 py-3">
          {/* A/B control: re-rank the same signal with learned memory on or off. */}
          {usedMemory ? (
            <div className="mb-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-eyebrow">Ranking memory</span>
                <div
                  role="group"
                  aria-label="Toggle learned memory"
                  className="inline-flex rounded-md border p-0.5"
                >
                  {(["with", "without"] as Mode[]).map((m) => (
                    <button
                      key={m}
                      type="button"
                      aria-pressed={mode === m}
                      onClick={() => setMode(m)}
                      className={cn(
                        "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                        mode === m
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {m === "with" ? "With memory" : "Without memory"}
                    </button>
                  ))}
                </div>
              </div>

              {mode === "without" ? (
                <p className="rounded-md border border-dashed bg-muted/30 px-2.5 py-1.5 text-xs leading-relaxed text-muted-foreground">
                  {canReorder ? (
                    chosenChanged ? (
                      <>
                        Without learned memory the engine would choose{" "}
                        <span className="font-medium text-foreground">
                          {rows[0].alt.action.title}
                        </span>{" "}
                        instead of{" "}
                        <span className="font-medium text-foreground">
                          {alternatives[withChosenIndex].action.title}
                        </span>
                        . Scores below are the memory-free base values.
                      </>
                    ) : (
                      <>
                        The winning play holds without memory, but base scores
                        (shown below) differ from the learned ranking.
                      </>
                    )
                  ) : (
                    <>
                      Base ranking signals only.{" "}
                      <span className="font-medium text-foreground">
                        {movedCount}
                      </span>{" "}
                      play{movedCount === 1 ? " was" : "s were"} re-weighted by
                      prior outcomes (highlighted below). Exact memory-free scores
                      need a re-run with memory disabled.
                    </>
                  )}
                </p>
              ) : (
                <p className="rounded-md border border-dashed bg-primary/[0.05] px-2.5 py-1.5 text-xs leading-relaxed text-muted-foreground">
                  Learned memory re-weighted{" "}
                  <span className="font-medium text-foreground">
                    {movedCount}
                  </span>{" "}
                  of {count} plays from prior approvals and rejections on similar
                  accounts.
                </p>
              )}
            </div>
          ) : (
            <p className="mb-3 text-xs text-muted-foreground">
              No learned signal changed this ranking yet: it is based on base
              expected value alone.
            </p>
          )}

          <ul className="space-y-2">
            {rows.map((row, i) => {
              const { alt, signal, chosen, score } = row;
              // In the lens fallback we keep the engine ordering, so dim the
              // memory tag instead of pretending the ranking moved.
              const lensFallback = mode === "without" && !canReorder;
              return (
                <li
                  key={`${alt.action.key}-${i}`}
                  className={cn(
                    "rounded-lg border px-3 py-2.5 transition-colors",
                    chosen
                      ? "border-primary/30 bg-primary/5"
                      : "border-border bg-muted/30",
                    lensFallback && signal && "ring-1 ring-inset ring-border",
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] font-semibold tabular text-muted-foreground">
                          #{i + 1}
                        </span>
                        <p className="truncate text-sm font-medium text-foreground/90">
                          {alt.action.title}
                        </p>
                        {chosen && (
                          <Badge variant="success">
                            <Trophy className="h-3 w-3" />
                            {mode === "without" && canReorder ? "Base pick" : "Chosen"}
                          </Badge>
                        )}
                        {signal && mode === "with" && (
                          <MemoryTag signal={signal} />
                        )}
                        {signal && lensFallback && (
                          <Badge variant="muted">memory hidden</Badge>
                        )}
                      </div>
                    </div>
                    <ScoreBar score={score} chosen={chosen} />
                  </div>

                  {alt.rationale && (
                    <p className="mt-1.5 text-xs leading-relaxed text-foreground/70">
                      {alt.rationale}
                    </p>
                  )}

                  {!chosen && alt.why_not && (
                    <p className="mt-1.5 flex gap-1.5 rounded-md border-l-2 border-muted-foreground/40 bg-muted/40 px-2 py-1 text-xs text-muted-foreground">
                      <span className="font-semibold text-foreground/80">
                        Why not:
                      </span>
                      <span className="text-foreground/70">{alt.why_not}</span>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

export default Alternatives;
