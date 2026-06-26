"use client";

import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { AccountTable } from "@/components/account-table";
import { getAccounts } from "@/lib/api";
import type { Account } from "@/lib/types";

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const ctrl = new AbortController();
    void getAccounts(ctrl.signal).then(setAccounts);
    return () => ctrl.abort();
  }, []);

  const filtered = useMemo(() => {
    if (!accounts) return [];
    const q = query.trim().toLowerCase();
    if (!q) return accounts;
    return accounts.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.account_id.toLowerCase().includes(q) ||
        a.domain.toLowerCase().includes(q),
    );
  }, [accounts, query]);

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-eyebrow">Portfolio</div>
          <h1 className="mt-1 text-display">Accounts</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Sort by health, risk, or ARR. Click through for the full account 360.
          </p>
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search accounts"
            className="pl-9"
          />
        </div>
      </header>

      {accounts === null ? (
        <div className="panel p-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 py-3">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-24" />
              <Skeleton className="ml-auto h-4 w-16" />
            </div>
          ))}
        </div>
      ) : (
        <AccountTable accounts={filtered} />
      )}
    </div>
  );
}
