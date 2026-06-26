"use client";

import { useState } from "react";
import { ChevronDown, Layers, Trophy } from "lucide-react";

import { Badge } from "@/components/ui/badge";
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

export interface AlternativesProps {
  alternatives: Alternative[];
  className?: string;
}

export function Alternatives({ alternatives, className }: AlternativesProps) {
  const [open, setOpen] = useState(false);

  if (!alternatives || alternatives.length === 0) return null;

  const count = alternatives.length;
  const panelId = "considered-alternatives";

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
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <ul id={panelId} className="space-y-2 border-t px-3 py-3">
          {alternatives.map((alt, i) => {
            const chosen = alt.chosen ?? i === 0;
            return (
              <li
                key={`${alt.action.key}-${i}`}
                className={cn(
                  "rounded-lg border px-3 py-2.5",
                  chosen
                    ? "border-primary/30 bg-primary/5"
                    : "border-border bg-muted/30",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[11px] font-semibold tabular text-muted-foreground">
                        #{i + 1}
                      </span>
                      <p className="truncate text-sm font-medium text-foreground/90">
                        {alt.action.title}
                      </p>
                      {chosen && (
                        <Badge variant="success">
                          <Trophy className="h-3 w-3" />
                          Chosen
                        </Badge>
                      )}
                    </div>
                  </div>
                  <ScoreBar score={alt.score} chosen={chosen} />
                </div>

                {alt.rationale && (
                  <p className="mt-1.5 text-xs leading-relaxed text-foreground/70">
                    {alt.rationale}
                  </p>
                )}

                {!chosen && alt.why_not && (
                  <p className="mt-1.5 flex gap-1.5 rounded-md border-l-2 border-muted-foreground/40 bg-muted/40 px-2 py-1 text-xs text-muted-foreground">
                    <span className="font-semibold text-foreground/80">Why not:</span>
                    <span className="text-foreground/70">{alt.why_not}</span>
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default Alternatives;
