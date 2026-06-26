"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpDown, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Account, RiskLevel } from "@/lib/types";

type SortKey = "name" | "health_score" | "risk_level" | "arr";
type SortDir = "asc" | "desc";

const RISK_ORDER: Record<string, number> = { high: 3, medium: 2, low: 1 };

export function riskVariant(
  risk: RiskLevel,
): "danger" | "warning" | "success" | "muted" {
  switch (String(risk).toLowerCase()) {
    case "high":
      return "danger";
    case "medium":
      return "warning";
    case "low":
      return "success";
    default:
      return "muted";
  }
}

export function healthTone(score: number): string {
  if (score >= 70) return "bg-emerald-500";
  if (score >= 45) return "bg-amber-500";
  return "bg-rose-500";
}

export function formatArr(arr: number): string {
  if (arr >= 1_000_000) return `$${(arr / 1_000_000).toFixed(1)}M`;
  if (arr >= 1_000) return `$${Math.round(arr / 1_000)}K`;
  return `$${arr}`;
}

function HealthBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score));
  return (
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
  { key: "health_score", label: "Health" },
  { key: "risk_level", label: "Risk" },
  { key: "arr", label: "ARR", align: "right" },
];

export interface AccountTableProps {
  accounts: Account[];
  className?: string;
}

export function AccountTable({ accounts, className }: AccountTableProps) {
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
      setSortDir(key === "name" ? "asc" : "desc");
    }
  };

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-card",
        className,
      )}
    >
      <table className="w-full border-collapse text-sm">
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
                    {account.last_signal}
                  </div>
                </Link>
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
              <td
                colSpan={5}
                className="px-4 py-10 text-center text-sm text-muted-foreground"
              >
                No accounts to show.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default AccountTable;
