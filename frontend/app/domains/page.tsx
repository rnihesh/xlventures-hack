"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Compass,
  FileJson,
  Loader2,
  Play,
  Plus,
  Trash2,
} from "lucide-react";

import { DomainCard } from "@/components/domain-card";
import { DomainOverview } from "@/components/domain-overview";
import type { DomainSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";
import {
  deletePack,
  getDomains,
  savePack,
  validatePack,
  type PackSummary,
} from "@/lib/api/domains";
import { toast } from "@/components/ui/toast";
import { getActiveDomain, setActiveDomain } from "@/lib/active-domain";

const FALLBACK: DomainSummary[] = [
  {
    key: "customer_success",
    display_name: "Customer Success",
    actions_count: 8,
    decision_points_count: 5,
    source: "base",
  },
  {
    key: "revenue_expansion",
    display_name: "Revenue Expansion",
    actions_count: 6,
    decision_points_count: 4,
    source: "base",
  },
  {
    key: "collections",
    display_name: "Collections",
    actions_count: 5,
    decision_points_count: 3,
    source: "base",
  },
];

// A minimal, valid pack so the textarea is runnable the moment the page loads.
const EXAMPLE_YAML = `domain: field_service
display_name: "Field Service Dispatch"
signals:
  - key: sla_breach_risk
    label: "Work order at risk of breaching its SLA"
    source_type: ticket
decision_points:
  sla_at_risk:
    label: "SLA at risk"
    description: "An open work order may miss its committed SLA."
    trigger_signals: [sla_breach_risk]
    primary_kpi: sla_attainment
    default_persona: dispatcher
actions:
  - key: expedite_dispatch
    title: "Expedite dispatch"
    description: "Assign the nearest qualified technician now."
    eligible_points: [sla_at_risk]
kpis:
  - key: sla_attainment
    label: "SLA Attainment"
    unit: percent
    target: ">= 95"
`;

// The persisted active pack wins when it is present in the list; otherwise the
// flagship Customer Success pack is the default active selection.
function resolveActive(list: DomainSummary[]): string | null {
  const stored = getActiveDomain();
  if (list.some((d) => d.key === stored)) return stored;
  return (
    list.find((d) => d.key === "customer_success")?.key ?? list[0]?.key ?? null
  );
}

export default function DomainsPage() {
  const router = useRouter();
  const [domains, setDomains] = useState<DomainSummary[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (): Promise<DomainSummary[]> => {
    const res = await getDomains();
    const list = Array.isArray(res) && res.length > 0 ? res : FALLBACK;
    setDomains(list);
    return list;
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const list = await load();
        if (alive) setActive(resolveActive(list));
      } catch {
        if (alive) {
          setDomains(FALLBACK);
          setActive(resolveActive(FALLBACK));
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [load]);

  const handleActivate = (key: string) => {
    setActive(key);
    setActiveDomain(key);
    const name = domains?.find((d) => d.key === key)?.display_name ?? key;
    toast(`${name} is now the active pack`, {
      description: "New runs default to this domain on the Run page.",
      variant: "success",
    });
  };

  const handleRunDecision = (key: string) => {
    setActiveDomain(key);
    router.push(`/run?domain=${encodeURIComponent(key)}`);
  };

  const handleDelete = async (key: string, name: string) => {
    try {
      await deletePack(key);
      toast(`Removed ${name}`, {
        description: "The uploaded pack is gone for your org.",
        variant: "success",
      });
      if (active === key) setActive(null);
      const list = await load();
      setActive((prev) => prev ?? resolveActive(list));
    } catch (err) {
      toast("Could not remove pack", {
        description: err instanceof Error ? err.message : "Unknown error",
        variant: "error",
      });
    }
  };

  return (
    <div className="flex flex-1 flex-col">
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
                playbooks in YAML. Paste one below to add a brand new use case in
                under a minute, then run a decision on it immediately.
              </p>
            </div>
          </div>
          <code className="shrink-0 rounded-md border border-border bg-background/70 px-3 py-1.5 font-mono text-xs text-muted-foreground">
            packs/{active ?? "domain"}.yaml
          </code>
        </div>

        <AddDomainPanel
          onSaved={async (key) => {
            const list = await load();
            setActive(key);
            setActiveDomain(key);
            return list;
          }}
          onRun={handleRunDecision}
        />

        {loading || !domains ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-56 rounded-lg" />
            ))}
          </div>
        ) : domains.length === 0 ? (
          <div className="panel">
            <EmptyState
              icon={Boxes}
              title="No domain packs found"
              description="Paste a pack YAML above to repoint the engine at a new use case."
            />
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {domains.map((d) => (
              <div key={d.key} className="flex flex-col gap-2">
                <DomainCard
                  domain={d}
                  active={active === d.key}
                  onActivate={handleActivate}
                />
                <div className="flex items-center justify-between px-1">
                  <button
                    type="button"
                    onClick={() => handleRunDecision(d.key)}
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
                  >
                    <Play className="h-3.5 w-3.5" />
                    Run a decision
                  </button>
                  {d.editable ? (
                    <button
                      type="button"
                      onClick={() => handleDelete(d.key, d.display_name)}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Remove
                    </button>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
                      Base
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Domain understanding: make the active business legible. The overview
            shows the process, journey, decision points (and the agent roster
            each triggers), and the success metrics for the selected pack. */}
        {active ? (
          <div className="mt-12">
            <div className="mb-5 flex items-center gap-3 border-b border-border pb-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
                <Compass className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-sm font-medium text-muted-foreground">
                  Domain understanding
                </h2>
                <p className="text-lg font-semibold tracking-tight">
                  The business we understand, and where the platform intervenes
                </p>
              </div>
            </div>
            <DomainOverview domain={active} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add a domain: paste YAML, validate, save, then run a decision on it.
// ---------------------------------------------------------------------------
function AddDomainPanel({
  onSaved,
  onRun,
}: {
  onSaved: (key: string) => Promise<unknown> | void;
  onRun: (key: string) => void;
}) {
  const [yaml, setYaml] = useState(EXAMPLE_YAML);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [summary, setSummary] = useState<PackSummary | null>(null);
  const [savedDomain, setSavedDomain] = useState<string | null>(null);

  const clearResult = () => {
    setErrors([]);
    setSavedDomain(null);
  };

  const handleValidate = async () => {
    setValidating(true);
    clearResult();
    try {
      const res = await validatePack(yaml);
      setSummary(res.summary);
      setErrors(res.ok ? [] : res.errors);
      if (res.ok) {
        toast("Pack is valid", {
          description: "Save it to add the domain for your org.",
          variant: "success",
        });
      }
    } finally {
      setValidating(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    clearResult();
    try {
      const res = await savePack(yaml);
      setSummary(res.summary as unknown as PackSummary);
      setSavedDomain(res.domain);
      await onSaved(res.domain);
      toast(`${res.display_name ?? res.domain} added`, {
        description: "It is now in your domain list and ready to run.",
        variant: "success",
      });
    } catch (err) {
      const e = err as Error & { errors?: string[] };
      setErrors(e.errors?.length ? e.errors : [e.message]);
      setSummary(null);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-8 overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center gap-3 border-b border-border px-5 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
          <Plus className="h-5 w-5" />
        </div>
        <div>
          <h3 className="text-sm font-semibold tracking-tight">Add a domain</h3>
          <p className="text-xs text-muted-foreground">
            Paste a domain pack YAML. It is validated against the pack schema and
            stored for your org. No redeploy.
          </p>
        </div>
      </div>

      <div className="grid gap-5 p-5 lg:grid-cols-2">
        <div className="flex flex-col gap-3">
          <label className="text-xs font-medium text-muted-foreground">
            Domain pack (YAML)
          </label>
          <Textarea
            value={yaml}
            onChange={(e) => {
              setYaml(e.target.value);
              clearResult();
            }}
            spellCheck={false}
            className="min-h-[320px] resize-y font-mono text-xs leading-relaxed"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              onClick={handleValidate}
              disabled={validating || saving}
            >
              {validating ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-2 h-4 w-4" />
              )}
              Validate
            </Button>
            <Button onClick={handleSave} disabled={saving || validating}>
              {saving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-2 h-4 w-4" />
              )}
              Save domain
            </Button>
            {savedDomain ? (
              <Button variant="secondary" onClick={() => onRun(savedDomain)}>
                <Play className="mr-2 h-4 w-4" />
                Run a decision
              </Button>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <label className="text-xs font-medium text-muted-foreground">
            Result
          </label>

          {errors.length > 0 ? (
            <div className="rounded-lg border border-destructive/40 bg-destructive/[0.06] p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-destructive">
                <AlertTriangle className="h-4 w-4" />
                {errors.length} issue{errors.length === 1 ? "" : "s"} to fix
              </div>
              <ul className="space-y-1 text-xs text-destructive/90">
                {errors.map((msg, i) => (
                  <li key={i} className="font-mono">
                    {msg}
                  </li>
                ))}
              </ul>
            </div>
          ) : summary ? (
            <div className="rounded-lg border border-border bg-background/50 p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                {summary.display_name}
                <code className="font-mono text-xs text-muted-foreground">
                  {summary.domain}
                </code>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <SummaryStat label="Decisions" value={summary.decision_points} />
                <SummaryStat label="Actions" value={summary.actions} />
                <SummaryStat label="Policies" value={summary.policies} />
                <SummaryStat label="Signals" value={summary.signals} />
                <SummaryStat label="KPIs" value={summary.kpis} />
                <SummaryStat label="Playbooks" value={summary.playbooks} />
              </div>
              {summary.action_titles.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {summary.action_titles.map((t) => (
                    <span
                      key={t}
                      className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] text-secondary-foreground"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
              Validate to preview the decision points, actions, and policies this
              pack declares.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border bg-card p-2">
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
    </div>
  );
}
