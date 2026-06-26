"use client";

import {
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Lock,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { PolicyGate } from "@/lib/types";

// Gates may carry an advisory severity from the engine; PolicyGate keeps it
// optional so this widened view stays compatible with the shared type.
export interface PolicyGateView extends PolicyGate {
  severity?: string;
}

interface PolicyPanelProps {
  gates: PolicyGateView[];
  /** Optional domain label, shown in the header for context. */
  domain?: string;
  className?: string;
}

type StatusKey = "pass" | "warn" | "fail";

function normalizeStatus(status: string): StatusKey {
  if (status === "fail") return "fail";
  if (status === "warn") return "warn";
  return "pass";
}

const STATUS_META: Record<
  StatusKey,
  {
    label: string;
    icon: typeof CheckCircle2;
    badge: "success" | "warning" | "danger";
    tone: string;
  }
> = {
  pass: {
    label: "Pass",
    icon: CheckCircle2,
    badge: "success",
    tone: "text-primary",
  },
  warn: {
    label: "Warn",
    icon: AlertTriangle,
    badge: "warning",
    tone: "text-primary",
  },
  fail: {
    label: "Fail",
    icon: XCircle,
    badge: "danger",
    tone: "text-destructive",
  },
};

export function PolicyPanel({ gates, domain, className }: PolicyPanelProps) {
  const list = gates ?? [];
  const failed = list.filter((g) => normalizeStatus(g.status) === "fail").length;
  const warned = list.filter((g) => normalizeStatus(g.status) === "warn").length;
  const passed = list.filter((g) => normalizeStatus(g.status) === "pass").length;
  const holding = list.some((g) => g.requires_approval);

  const headerBadge = holding ? (
    <Badge variant="warning" className="gap-1">
      <Lock className="h-3 w-3" />
      Needs approval
    </Badge>
  ) : failed > 0 ? (
    <Badge variant="danger" className="gap-1">
      <XCircle className="h-3 w-3" />
      {failed} failing
    </Badge>
  ) : warned > 0 ? (
    <Badge variant="warning" className="gap-1">
      <AlertTriangle className="h-3 w-3" />
      {warned} warning{warned > 1 ? "s" : ""}
    </Badge>
  ) : (
    <Badge variant="success" className="gap-1">
      <CheckCircle2 className="h-3 w-3" />
      All clear
    </Badge>
  );

  return (
    <Card className={cn(holding && "border-primary/40", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide">
              {holding ? (
                <ShieldAlert className="h-3.5 w-3.5 text-primary" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5 text-primary" />
              )}
              Policy guardrails
              {domain ? (
                <span className="font-mono text-[10px] normal-case text-muted-foreground">
                  {domain}
                </span>
              ) : null}
            </CardDescription>
            <CardTitle className="text-base">
              {list.length === 0
                ? "No policy gates evaluated"
                : `${passed} of ${list.length} gates cleared`}
            </CardTitle>
          </div>
          {list.length > 0 ? headerBadge : null}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {list.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">
            This recommendation has not been checked against the domain policy
            rules yet.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {list.map((gate) => {
              const meta = STATUS_META[normalizeStatus(gate.status)];
              const Icon = meta.icon;
              const flagged = gate.requires_approval;
              return (
                <li
                  key={gate.rule_id}
                  className={cn(
                    "flex items-start gap-3 px-6 py-3.5",
                    flagged && "bg-primary/[0.06]",
                  )}
                >
                  <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", meta.tone)} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">
                        {gate.description || gate.rule_id}
                      </span>
                      {flagged ? (
                        <Badge variant="warning" className="gap-1 px-1.5 py-0">
                          <Lock className="h-3 w-3" />
                          Forces approval
                        </Badge>
                      ) : null}
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      {gate.detail}
                    </p>
                    <span className="mt-1 inline-block font-mono text-[10px] text-muted-foreground/70">
                      {gate.rule_id}
                      {gate.severity ? ` - ${gate.severity}` : ""}
                    </span>
                  </div>
                  <Badge variant={meta.badge} className="shrink-0">
                    {meta.label}
                  </Badge>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default PolicyPanel;
