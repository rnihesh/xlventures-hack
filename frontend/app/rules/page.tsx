"use client";

// Configurable business rules editor.
//
// An org tailors a domain pack's policy rules and action catalog here without
// forking the base pack. The page loads the effective rules (base merged with
// the org override) via GET /rules/{domain}, lets the user add, edit, and
// remove entries, and persists the full desired lists as the org override via
// PUT /rules/{domain}. The policy engine and planner then read these rules for
// the org. Fully offline-safe: with no backend the view loads empty and Save
// surfaces a real error rather than crashing.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Plus,
  Trash2,
  Save,
  RotateCcw,
  ShieldCheck,
  ListChecks,
} from "lucide-react";

import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { getDomains } from "@/lib/api";
import type { DomainSummary } from "@/lib/types";
import { getActiveDomain } from "@/lib/active-domain";
import {
  getRules,
  saveRules,
  type RuleAction,
  type RulePolicy,
} from "@/lib/api/rules";

// The rule types the policy engine understands, surfaced as a friendly select.
const RULE_TYPES: { value: string; label: string }[] = [
  { value: "discount_cap", label: "Discount cap" },
  { value: "cooldown_window", label: "Cooldown window" },
  { value: "action_requires_approval", label: "Action requires approval" },
  { value: "confidence_floor", label: "Confidence floor" },
  { value: "field_threshold", label: "Field threshold" },
  { value: "advisory", label: "Advisory (human judgement)" },
];

const SEVERITIES = ["low", "medium", "high"];

// Editable policy: condition is held as JSON text so any rule type is editable;
// it is parsed back to an object on save.
interface EditPolicy {
  id: string;
  description: string;
  type: string;
  conditionText: string;
  severity: string;
  requires_approval: boolean;
}

function toEditPolicy(p: RulePolicy): EditPolicy {
  return {
    id: p.id,
    description: p.description ?? "",
    type: p.type ?? "advisory",
    conditionText: JSON.stringify(p.condition ?? {}),
    severity: p.severity ?? "medium",
    requires_approval: Boolean(p.requires_approval),
  };
}

function severityVariant(sev: string): "danger" | "warning" | "muted" {
  if (sev === "high") return "danger";
  if (sev === "medium") return "warning";
  return "muted";
}

export default function RulesPage() {
  const [domains, setDomains] = useState<DomainSummary[]>([]);
  const [domain, setDomain] = useState<string>(getActiveDomain());
  const [displayName, setDisplayName] = useState<string>("");
  const [policies, setPolicies] = useState<EditPolicy[]>([]);
  const [actions, setActions] = useState<RuleAction[]>([]);
  const [hasOverride, setHasOverride] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Load the domain list once for the pack switcher.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const list = await getDomains();
        if (alive && Array.isArray(list) && list.length > 0) setDomains(list);
      } catch {
        /* selector falls back to the single active domain */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const load = useCallback(async (dom: string) => {
    setLoading(true);
    try {
      const view = await getRules(dom);
      setDisplayName(view.display_name);
      setPolicies(view.policies.map(toEditPolicy));
      setActions(
        view.actions.map((a) => ({
          key: a.key,
          title: a.title ?? "",
          description: a.description ?? "",
          eligibility: a.eligibility ?? "",
        })),
      );
      setHasOverride(view.has_override);
      setDirty(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(domain);
  }, [domain, load]);

  const markDirty = () => setDirty(true);

  // ---- Policy mutations ----------------------------------------------------
  const updatePolicy = (i: number, patch: Partial<EditPolicy>) => {
    setPolicies((prev) =>
      prev.map((p, idx) => (idx === i ? { ...p, ...patch } : p)),
    );
    markDirty();
  };

  const removePolicy = (i: number) => {
    setPolicies((prev) => prev.filter((_, idx) => idx !== i));
    markDirty();
  };

  const addPolicy = () => {
    setPolicies((prev) => [
      ...prev,
      {
        id: "",
        description: "",
        type: "advisory",
        conditionText: "{}",
        severity: "medium",
        requires_approval: false,
      },
    ]);
    markDirty();
  };

  // ---- Action mutations ----------------------------------------------------
  const updateAction = (i: number, patch: Partial<RuleAction>) => {
    setActions((prev) =>
      prev.map((a, idx) => (idx === i ? { ...a, ...patch } : a)),
    );
    markDirty();
  };

  const removeAction = (i: number) => {
    setActions((prev) => prev.filter((_, idx) => idx !== i));
    markDirty();
  };

  const addAction = () => {
    setActions((prev) => [
      ...prev,
      { key: "", title: "", description: "", eligibility: "" },
    ]);
    markDirty();
  };

  // ---- Persist -------------------------------------------------------------
  const buildPolicies = (): RulePolicy[] | null => {
    const out: RulePolicy[] = [];
    const seen = new Set<string>();
    for (const p of policies) {
      const id = p.id.trim();
      if (!id) {
        toast("Every policy rule needs an id", { variant: "error" });
        return null;
      }
      if (seen.has(id)) {
        toast(`Duplicate rule id: ${id}`, { variant: "error" });
        return null;
      }
      seen.add(id);
      let condition: Record<string, unknown> = {};
      const text = p.conditionText.trim();
      if (text) {
        try {
          const parsed = JSON.parse(text);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            condition = parsed as Record<string, unknown>;
          } else {
            throw new Error("not an object");
          }
        } catch {
          toast(`Condition for "${id}" must be a JSON object`, { variant: "error" });
          return null;
        }
      }
      out.push({
        id,
        description: p.description.trim(),
        type: p.type,
        condition,
        severity: p.severity,
        requires_approval: p.requires_approval,
      });
    }
    return out;
  };

  const buildActions = (): RuleAction[] | null => {
    const out: RuleAction[] = [];
    const seen = new Set<string>();
    for (const a of actions) {
      const key = a.key.trim();
      if (!key) {
        toast("Every action needs a key", { variant: "error" });
        return null;
      }
      if (seen.has(key)) {
        toast(`Duplicate action key: ${key}`, { variant: "error" });
        return null;
      }
      seen.add(key);
      out.push({
        key,
        title: (a.title ?? "").trim(),
        description: (a.description ?? "").trim(),
        eligibility: (a.eligibility ?? "").trim(),
      });
    }
    return out;
  };

  const handleSave = async () => {
    const builtPolicies = buildPolicies();
    if (builtPolicies === null) return;
    const builtActions = buildActions();
    if (builtActions === null) return;

    setSaving(true);
    try {
      const view = await saveRules(domain, {
        policies: builtPolicies,
        actions: builtActions,
      });
      setDisplayName(view.display_name);
      setPolicies(view.policies.map(toEditPolicy));
      setActions(
        view.actions.map((a) => ({
          key: a.key,
          title: a.title ?? "",
          description: a.description ?? "",
          eligibility: a.eligibility ?? "",
        })),
      );
      setHasOverride(view.has_override);
      setDirty(false);
      toast("Rules saved for your workspace", {
        description: "The policy engine and planner now apply these rules.",
        variant: "success",
      });
    } catch {
      toast("Could not save rules", {
        description: "The backend was unreachable. Try again.",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setSaving(true);
    try {
      await saveRules(domain, {});
      toast("Reverted to the base pack", { variant: "success" });
      await load(domain);
    } catch {
      toast("Could not reset rules", { variant: "error" });
    } finally {
      setSaving(false);
    }
  };

  const domainOptions = useMemo(() => {
    if (domains.length > 0) return domains;
    return [{ key: domain, display_name: displayName || domain }] as DomainSummary[];
  }, [domains, domain, displayName]);

  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-8">
      <PageHeader
        eyebrow="Governance"
        title="Business rules"
        description={`Configure the policy guardrails and action catalog the engine applies for your workspace. Edits are saved as an org override on top of the base ${displayName || domain} pack.`}
        actions={
          <>
            <Select
              aria-label="Domain pack"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="w-52"
            >
              {domainOptions.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.display_name}
                </option>
              ))}
            </Select>
            <Badge variant={hasOverride ? "success" : "muted"}>
              {hasOverride ? "Customized" : "Base pack"}
            </Badge>
          </>
        }
      />

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : (
        <Tabs defaultValue="policies">
          <TabsList>
            <TabsTrigger value="policies">
              <ShieldCheck className="mr-1.5 h-4 w-4" aria-hidden />
              Policy rules ({policies.length})
            </TabsTrigger>
            <TabsTrigger value="actions">
              <ListChecks className="mr-1.5 h-4 w-4" aria-hidden />
              Actions ({actions.length})
            </TabsTrigger>
          </TabsList>

          {/* ---- Policy rules ------------------------------------------- */}
          <TabsContent value="policies" className="space-y-4">
            {policies.map((p, i) => (
              <Card key={`policy-${i}`}>
                <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
                  <div className="flex-1 space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Input
                        aria-label="Rule id"
                        placeholder="rule_id"
                        value={p.id}
                        onChange={(e) => updatePolicy(i, { id: e.target.value })}
                        className="h-8 max-w-[14rem] font-mono text-xs"
                      />
                      <Badge variant={severityVariant(p.severity)}>
                        {p.severity}
                      </Badge>
                      {p.requires_approval && (
                        <Badge variant="info">requires approval</Badge>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Remove rule"
                    onClick={() => removePolicy(i)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Description
                    </label>
                    <Input
                      placeholder="What this guardrail enforces"
                      value={p.description}
                      onChange={(e) =>
                        updatePolicy(i, { description: e.target.value })
                      }
                    />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-muted-foreground">
                        Type
                      </label>
                      <Select
                        value={p.type}
                        onChange={(e) =>
                          updatePolicy(i, { type: e.target.value })
                        }
                      >
                        {RULE_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-muted-foreground">
                        Severity
                      </label>
                      <Select
                        value={p.severity}
                        onChange={(e) =>
                          updatePolicy(i, { severity: e.target.value })
                        }
                      >
                        {SEVERITIES.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Condition / threshold (JSON)
                    </label>
                    <Textarea
                      spellCheck={false}
                      value={p.conditionText}
                      onChange={(e) =>
                        updatePolicy(i, { conditionText: e.target.value })
                      }
                      className="min-h-[60px] font-mono text-xs"
                      placeholder='{"max_pct": 15}'
                    />
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={p.requires_approval}
                      onChange={(e) =>
                        updatePolicy(i, { requires_approval: e.target.checked })
                      }
                      className="h-4 w-4 rounded border-input accent-[var(--primary)]"
                    />
                    Requires human approval when tripped
                  </label>
                </CardContent>
              </Card>
            ))}
            <Button variant="outline" onClick={addPolicy} className="w-full">
              <Plus className="mr-1.5 h-4 w-4" /> Add policy rule
            </Button>
          </TabsContent>

          {/* ---- Actions ------------------------------------------------ */}
          <TabsContent value="actions" className="space-y-4">
            {actions.map((a, i) => (
              <Card key={`action-${i}`}>
                <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
                  <Input
                    aria-label="Action key"
                    placeholder="action_key"
                    value={a.key}
                    onChange={(e) => updateAction(i, { key: e.target.value })}
                    className="h-8 max-w-[16rem] font-mono text-xs"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Remove action"
                    onClick={() => removeAction(i)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Title
                    </label>
                    <Input
                      placeholder="Human readable play name"
                      value={a.title}
                      onChange={(e) =>
                        updateAction(i, { title: e.target.value })
                      }
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Description
                    </label>
                    <Textarea
                      placeholder="What the play does and when it helps"
                      value={a.description}
                      onChange={(e) =>
                        updateAction(i, { description: e.target.value })
                      }
                      className="min-h-[60px]"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Eligibility
                    </label>
                    <Input
                      placeholder="When this action is eligible"
                      value={a.eligibility ?? ""}
                      onChange={(e) =>
                        updateAction(i, { eligibility: e.target.value })
                      }
                    />
                  </div>
                </CardContent>
              </Card>
            ))}
            <Button variant="outline" onClick={addAction} className="w-full">
              <Plus className="mr-1.5 h-4 w-4" /> Add action
            </Button>
          </TabsContent>
        </Tabs>
      )}

      <Separator className="my-6" />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {dirty
            ? "You have unsaved changes."
            : hasOverride
              ? "Showing your saved workspace rules."
              : "Showing the base pack rules."}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={handleReset}
            disabled={saving || loading || !hasOverride}
          >
            <RotateCcw className="mr-1.5 h-4 w-4" /> Reset to base
          </Button>
          <Button onClick={handleSave} disabled={saving || loading || !dirty}>
            <Save className="mr-1.5 h-4 w-4" />
            {saving ? "Saving..." : "Save rules"}
          </Button>
        </div>
      </div>
    </div>
  );
}
