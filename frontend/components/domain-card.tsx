"use client";

import { Boxes, GitBranch, CheckCircle2, Plug } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface DomainSummary {
  key: string;
  display_name: string;
  actions_count: number;
  decision_points_count: number;
}

export function DomainCard({
  domain,
  active = false,
  onActivate,
}: {
  domain: DomainSummary;
  active?: boolean;
  onActivate?: (key: string) => void;
}) {
  return (
    <Card
      className={cn(
        "relative flex flex-col transition-colors",
        active
          ? "border-primary/60 bg-primary/[0.04] shadow-md"
          : "hover:border-primary/30"
      )}
    >
      {active ? (
        <span className="absolute right-4 top-4 inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-500 ring-1 ring-inset ring-emerald-500/20">
          <CheckCircle2 className="h-3 w-3" />
          Active
        </span>
      ) : null}
      <CardHeader className="pb-3">
        <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
          <Boxes className="h-5 w-5" />
        </div>
        <CardTitle className="text-base">{domain.display_name}</CardTitle>
        <CardDescription className="font-mono text-xs">
          {domain.key}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col justify-between gap-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-border bg-background/50 p-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Plug className="h-3.5 w-3.5" />
              Actions
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">
              {domain.actions_count}
            </div>
          </div>
          <div className="rounded-lg border border-border bg-background/50 p-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <GitBranch className="h-3.5 w-3.5" />
              Decision points
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">
              {domain.decision_points_count}
            </div>
          </div>
        </div>
        <Button
          variant={active ? "secondary" : "default"}
          className="w-full"
          disabled={active}
          onClick={() => onActivate?.(domain.key)}
        >
          {active ? "Currently active" : "Make active"}
        </Button>
      </CardContent>
    </Card>
  );
}

export default DomainCard;
