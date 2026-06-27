"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpDown, ChevronRight, Download, Loader2, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Account, RiskLevel } from "@/lib/types";

type SortKey = "name" | "domain" | "health_score" | "risk_level" | "arr";
type SortDir = "asc" | "desc";

const RISK_ORDER: Record<string, number> = { high: 3, medium: 2, low: 1 };

// The risk queue and portfolio mix domain packs (customer success, collections,
// SaaS sales). A short, human label keeps the mix legible without leaking the
// raw pack key into the UI.
const DOMAIN_LABELS: Record<string, string> = {
  customer_success: "Customer Success",
  collections: "Collections",
  saas_sales: "SaaS Sales",
};

export function domainLabel(domain: string): string {
  const key = String(domain ?? "").toLowerCase();
  if (DOMAIN_LABELS[key]) return DOMAIN_LABELS[key];
  if (!key) return "General";
  return key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// Subtle grayscale chip naming the domain pack an account belongs to. Kept
// neutral (no accent hue) so it labels without competing with risk signals.
export function DomainBadge({
  domain,
  className,
}: {
  domain: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground",
        className,
      )}
    >
      {domainLabel(domain)}
    </span>
  );
}

export function riskVariant(
  risk: RiskLevel,
): "danger" | "warning" | "success" | "muted" {
  switch (String(risk).toLowerCase()) {
    case "high":
      return "danger";
    case "medium":
      return "warning";
    case "low":
      return "muted";
    default:
      return "muted";
  }
}

export function healthTone(score: number): string {
  if (score >= 45) return "bg-primary";
  return "bg-destructive";
}

// Plain-language label so a non-expert can read a health number at a glance.
export function healthLabel(score: number): string {
  if (score >= 70) return "Healthy";
  if (score >= 45) return "Needs attention";
  return "At risk";
}

// A friendly one-liner describing what a risk level means for the account.
export function riskMeaning(risk: RiskLevel): string {
  switch (String(risk).toLowerCase()) {
    case "critical":
      return "Severe churn risk; immediate intervention needed.";
    case "high":
      return "Likely to churn or cut back without action soon.";
    case "medium":
      return "Some warning signs worth a proactive check-in.";
    case "low":
      return "Stable relationship with no pressing concerns.";
    default:
      return "Risk level not yet assessed.";
  }
}

export function formatArr(arr: number): string {
  if (arr >= 1_000_000) return `$${(arr / 1_000_000).toFixed(1)}M`;
  if (arr >= 1_000) return `$${Math.round(arr / 1_000)}K`;
  return `$${arr}`;
}

function HealthBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score));
  return (
    <div className="min-w-[8.5rem]">
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full transition-all", healthTone(pct))}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-7 text-right text-xs tabular text-muted-foreground">
          {Math.round(pct)}
        </span>
      </div>
      <span className="mt-1 block text-[11px] text-muted-foreground">
        {healthLabel(pct)}
      </span>
    </div>
  );
}

interface ColumnDef {
  key: SortKey;
  label: string;
  className?: string;
  align?: "left" | "right";
}

const COLUMNS: ColumnDef[] = [
  { key: "name", label: "Account" },
  { key: "domain", label: "Domain" },
  { key: "health_score", label: "Health score" },
  { key: "risk_level", label: "Churn risk" },
  { key: "arr", label: "Revenue (ARR)", align: "right" },
];

export interface AccountTableProps {
  accounts: Account[];
  className?: string;
  // Optional empty-state actions. When the list is empty and these are
  // provided, the table offers a clear way to populate the portfolio.
  onAddAccount?: () => void;
  onImportDemo?: () => void;
  importing?: boolean;
}

export function AccountTable({
  accounts,
  className,
  onAddAccount,
  onImportDemo,
  importing,
}: AccountTableProps) {
  const [sortKey, setSortKey] = React.useState<SortKey>("risk_level");
  const [sortDir, setSortDir] = React.useState<SortDir>("desc");

  const sorted = React.useMemo(() => {
    const rows = [...accounts];
    rows.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "name":
          cmp = a.name.localeCompare(b.name);
          break;
        case "domain":
          cmp = domainLabel(a.domain).localeCompare(domainLabel(b.domain));
          break;
        case "health_score":
          cmp = a.health_score - b.health_score;
          break;
        case "arr":
          cmp = a.arr - b.arr;
          break;
        case "risk_level":
          cmp =
            (RISK_ORDER[String(a.risk_level).toLowerCase()] ?? 0) -
            (RISK_ORDER[String(b.risk_level).toLowerCase()] ?? 0);
          break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [accounts, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "name" || key === "domain" ? "asc" : "desc");
    }
  };

  return (
    <div
      className={cn(
        "overflow-x-auto rounded-xl border border-border bg-card",
        className,
      )}
    >
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/40 text-left">
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cn(
                  "px-4 py-2.5 text-eyebrow font-semibold",
                  col.align === "right" && "text-right",
                )}
              >
                <button
                  type="button"
                  onClick={() => toggleSort(col.key)}
                  className={cn(
                    "inline-flex items-center gap-1 transition-colors hover:text-foreground",
                    col.align === "right" && "flex-row-reverse",
                    sortKey === col.key && "text-foreground",
                  )}
                >
                  {col.label}
                  <ArrowUpDown className="h-3 w-3 opacity-60" />
                </button>
              </th>
            ))}
            <th scope="col" className="w-10 px-4 py-2.5" />
          </tr>
        </thead>
        <tbody>
          {sorted.map((account) => (
            <tr
              key={account.account_id}
              className="group border-b border-border last:border-0 transition-colors hover:bg-accent/40"
            >
              <td className="px-4 py-3">
                <Link
                  href={`/accounts/${account.account_id}`}
                  className="block"
                >
                  <div className="font-medium text-foreground">
                    {account.name}
                  </div>
                  <div className="mt-0.5 line-clamp-1 max-w-md text-xs text-muted-foreground">
                    <span className="text-muted-foreground/70">
                      Latest signal:{" "}
                    </span>
                    {account.last_signal}
                  </div>
                </Link>
              </td>
              <td className="px-4 py-3">
                <DomainBadge domain={account.domain} />
              </td>
              <td className="px-4 py-3">
                <HealthBar score={account.health_score} />
              </td>
              <td className="px-4 py-3">
                <Badge variant={riskVariant(account.risk_level)}>
                  {String(account.risk_level)}
                </Badge>
              </td>
              <td className="px-4 py-3 text-right font-medium tabular">
                {formatArr(account.arr)}
              </td>
              <td className="px-4 py-3 text-right">
                <Link
                  href={`/accounts/${account.account_id}`}
                  aria-label={`Open ${account.name}`}
                  className="inline-flex text-muted-foreground transition-colors group-hover:text-foreground"
                >
                  <ChevronRight className="h-4 w-4" />
                </Link>
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={6} className="px-4 py-12 text-center">
                <p className="text-sm font-medium text-foreground">
                  No accounts yet
                </p>
                <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
                  {onAddAccount || onImportDemo
                    ? "Add your first account or import the demo set to get started."
                    : "No accounts to show."}
                </p>
                {(onAddAccount || onImportDemo) && (
                  <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                    {onAddAccount && (
                      <Button type="button" onClick={onAddAccount}>
                        <Plus className="h-4 w-4" />
                        Add account
                      </Button>
                    )}
                    {onImportDemo && (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={onImportDemo}
                        disabled={importing}
                      >
                        {importing ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Download className="h-4 w-4" />
                        )}
                        Import demo accounts
                      </Button>
                    )}
                  </div>
                )}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default AccountTable;
