"use client";

import { useEffect, useState } from "react";
import { Boxes, FileJson } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { DomainCard, type DomainSummary } from "@/components/domain-card";
import { getDomains } from "@/lib/api";

const FALLBACK: DomainSummary[] = [
  {
    key: "customer_success",
    display_name: "Customer Success",
    actions_count: 8,
    decision_points_count: 5,
  },
  {
    key: "revenue_expansion",
    display_name: "Revenue Expansion",
    actions_count: 6,
    decision_points_count: 4,
  },
  {
    key: "collections",
    display_name: "Collections",
    actions_count: 5,
    decision_points_count: 3,
  },
];

export default function DomainsPage() {
  const [domains, setDomains] = useState<DomainSummary[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = (await getDomains()) as DomainSummary[];
        const list = Array.isArray(res) && res.length > 0 ? res : FALLBACK;
        if (alive) {
          setDomains(list);
          setActive(list[0]?.key ?? null);
        }
      } catch {
        if (alive) {
          setDomains(FALLBACK);
          setActive(FALLBACK[0].key);
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
              <Boxes className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-sm font-medium text-muted-foreground">
                Domains
              </h1>
              <p className="text-lg font-semibold tracking-tight">
                Decision packs
              </p>
            </div>
          </div>
        </header>

        <div className="mx-auto w-full max-w-5xl px-6 py-8">
          {/* Headline: a new domain is config, not code */}
          <div className="mb-8 flex flex-col gap-3 rounded-xl border border-primary/30 bg-primary/[0.04] p-6 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <FileJson className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold tracking-tight">
                  Same engine. A new domain is configuration, not code.
                </h2>
                <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                  Each pack declares its actions, decision points, KPIs, and
                  playbooks in JSON. Swap the active pack to repoint the planner,
                  retriever, and memory at a brand new use case, no redeploy.
                </p>
              </div>
            </div>
            <code className="shrink-0 rounded-md border border-border bg-background/70 px-3 py-1.5 font-mono text-xs text-muted-foreground">
              packs/{active ?? "domain"}.json
            </code>
          </div>

          {loading || !domains ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="h-56 animate-pulse rounded-lg border border-border bg-muted/40"
                />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {domains.map((d) => (
                <DomainCard
                  key={d.key}
                  domain={d}
                  active={active === d.key}
                  onActivate={setActive}
                />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
