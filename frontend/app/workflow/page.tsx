"use client";

// Visual Workflow Studio.
//
// Renders the agent orchestration graph for a domain left to right and lets an
// org tune which selectable specialists run at each decision point. The planner
// always runs the always-on specialists; the selectable ones are toggled per
// decision point. Edits are local until saved; Save persists only the decision
// points that differ from the base pack (PUT rosters), and the backend reverts
// any omitted point to its default. Fully offline-safe: with no backend the
// view shows an error state and Save surfaces a real error rather than crashing.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  MarkerType,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Network,
  Save,
  RotateCcw,
  RefreshCw,
  Check,
  Lock,
  Radio,
  Route,
  ShieldCheck,
  UserCheck,
  Flag,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState, EmptyState } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { getDomains } from "@/lib/api";
import type { DomainSummary } from "@/lib/types";
import { getActiveDomain } from "@/lib/active-domain";
import {
  getWorkflow,
  putWorkflow,
  type WorkflowView,
  type WorkflowRosters,
} from "@/lib/api/workflow";

const ACCENT = "#D97757";
const EDGE_MUTED = "#d6d3d1";

// Prettify a capability key ("risk_scorer") into a label ("Risk Scorer").
function prettify(key: string): string {
  return key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// Same-set comparison ignoring order (rosters are sets of capabilities).
function sameSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sb = new Set(b);
  return a.every((x) => sb.has(x));
}

// --------------------------------------------------------------------------
// Custom node
// --------------------------------------------------------------------------

type NodeState = "fixed" | "active" | "inactive" | "alwayson";

type PipelineNodeData = {
  title: string;
  role: string;
  state: NodeState;
  clickable: boolean;
  Icon: LucideIcon;
  onToggle?: () => void;
};

type PipelineNode = Node<PipelineNodeData, "pipeline">;

function MiniSwitch({ on }: { on: boolean }) {
  return (
    <span
      className={cn(
        "relative inline-flex h-4 w-7 shrink-0 items-center rounded-full border transition-colors",
        on ? "border-primary bg-primary" : "border-border bg-muted",
      )}
      aria-hidden
    >
      <span
        className={cn(
          "absolute h-3 w-3 rounded-full bg-white shadow-sm transition-transform",
          on ? "translate-x-[14px]" : "translate-x-[2px]",
        )}
      />
    </span>
  );
}

function PipelineNodeView({ data }: NodeProps<PipelineNode>) {
  const { title, role, state, clickable, Icon, onToggle } = data;
  const isActive = state === "active";
  const isInactive = state === "inactive";

  const cardTone = isActive
    ? "border-primary/60 bg-card ring-1 ring-primary/30"
    : isInactive
      ? "border-dashed border-border bg-card opacity-45"
      : state === "alwayson"
        ? "border-border bg-secondary"
        : "border-border bg-card";

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle?.();
  };

  return (
    <div
      onClick={clickable ? onToggle : undefined}
      role={clickable ? "button" : undefined}
      aria-pressed={clickable ? isActive : undefined}
      className={cn(
        "relative w-[176px] select-none rounded-xl border py-2.5 pl-3 pr-2.5 shadow-sm transition-colors",
        cardTone,
        clickable ? "cursor-pointer hover:border-primary/70" : "cursor-default",
      )}
    >
      {isActive ? (
        <span
          className="absolute bottom-2 left-0 top-2 w-1 rounded-full bg-primary"
          aria-hidden
        />
      ) : null}

      <Handle
        type="target"
        position={Position.Left}
        className="!h-1.5 !w-1.5 !border-0 !bg-border"
      />

      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <Icon
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              isActive ? "text-primary" : "text-muted-foreground",
            )}
            aria-hidden
          />
          <span className="truncate text-[13px] font-semibold tracking-tight text-foreground">
            {title}
          </span>
        </div>
        {clickable ? (
          <button
            type="button"
            onClick={handleToggle}
            aria-label={isActive ? `Turn off ${title}` : `Turn on ${title}`}
            title={isActive ? "On (click to turn off)" : "Off (click to turn on)"}
            className="shrink-0 rounded p-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <MiniSwitch on={isActive} />
          </button>
        ) : null}
      </div>

      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          {role}
        </span>
        {clickable ? (
          <span
            className={cn(
              "rounded-full px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide",
              isActive
                ? "bg-primary/10 text-primary ring-1 ring-inset ring-primary/25"
                : "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
            )}
          >
            {isActive ? "On" : "Off"}
          </span>
        ) : (
          <span className="flex items-center gap-1 rounded-full bg-muted px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-muted-foreground ring-1 ring-inset ring-border">
            <Lock className="h-2.5 w-2.5" aria-hidden />
            {state === "alwayson" ? "always on" : "fixed"}
          </span>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="!h-1.5 !w-1.5 !border-0 !bg-border"
      />
    </div>
  );
}

const NODE_TYPES = { pipeline: PipelineNodeView };

// Module-scope to keep object identity stable across renders.
const PRO_OPTIONS = { hideAttribution: true };
const FIT_VIEW_OPTIONS = { padding: 0.16 };
const ROLE_ICON: Record<string, LucideIcon> = {
  signal: Radio,
  planner: Route,
  policy: ShieldCheck,
  hitl: UserCheck,
  commit: Flag,
};

// --------------------------------------------------------------------------
// Page
// --------------------------------------------------------------------------

export default function WorkflowPage() {
  const [domains, setDomains] = useState<DomainSummary[]>([]);
  const [domain, setDomain] = useState<string>(getActiveDomain());
  const [view, setView] = useState<WorkflowView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(false);

  // Selected decision point and the per-decision-point edited rosters.
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [edited, setEdited] = useState<Record<string, string[]>>({});
  // Server-effective rosters at last load, to compute the dirty state.
  const [original, setOriginal] = useState<Record<string, string[]>>({});

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

  const applyView = useCallback((v: WorkflowView) => {
    const rosters: Record<string, string[]> = {};
    for (const dp of v.decision_points) rosters[dp.key] = [...dp.roster];
    setView(v);
    setOriginal(rosters);
    setEdited(cloneRosters(rosters));
    setSelectedKey((prev) =>
      prev && v.decision_points.some((dp) => dp.key === prev)
        ? prev
        : v.decision_points[0]?.key ?? "",
    );
  }, []);

  const load = useCallback(
    async (dom: string, signal?: AbortSignal) => {
      setLoading(true);
      setError(false);
      setSavedAt(false);
      try {
        const v = await getWorkflow(dom, signal);
        applyView(v);
      } catch {
        setView(null);
        setError(true);
      } finally {
        setLoading(false);
      }
    },
    [applyView],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    void load(domain, ctrl.signal);
    return () => ctrl.abort();
  }, [domain, load]);

  // The selectable specialist candidates (the toggles), in order.
  const selectable = useMemo(
    () => (view ? view.specialists.filter((s) => !s.always_on) : []),
    [view],
  );
  const selectableCaps = useMemo(
    () => new Set(selectable.map((s) => s.capability)),
    [selectable],
  );
  const alwaysOnCaps = useMemo(() => {
    const set = new Set<string>(view?.always_on ?? []);
    for (const s of view?.specialists ?? [])
      if (s.always_on) set.add(s.capability);
    return set;
  }, [view]);

  const selectedDp = useMemo(
    () => view?.decision_points.find((dp) => dp.key === selectedKey) ?? null,
    [view, selectedKey],
  );
  const currentRoster = edited[selectedKey] ?? [];

  const isOverridden = useCallback(
    (key: string, base: string[]) => !sameSet(edited[key] ?? [], base),
    [edited],
  );

  const selectedOverridden = selectedDp
    ? isOverridden(selectedDp.key, selectedDp.base_roster)
    : false;
  const anyOverridden = useMemo(
    () =>
      (view?.decision_points ?? []).some((dp) =>
        isOverridden(dp.key, dp.base_roster),
      ),
    [view, isOverridden],
  );

  const dirty = useMemo(() => {
    const keys = new Set([...Object.keys(edited), ...Object.keys(original)]);
    for (const k of keys) {
      if (!sameSet(edited[k] ?? [], original[k] ?? [])) return true;
    }
    return false;
  }, [edited, original]);

  // Toggle a selectable specialist in/out of the selected point's roster.
  const toggleCap = useCallback(
    (cap: string) => {
      if (!selectedKey) return;
      setSavedAt(false);
      setEdited((prev) => {
        const cur = prev[selectedKey] ?? [];
        const next = cur.includes(cap)
          ? cur.filter((c) => c !== cap)
          : [...cur, cap];
        return { ...prev, [selectedKey]: next };
      });
    },
    [selectedKey],
  );

  // --- Graph model --------------------------------------------------------
  const { nodes, edges } = useMemo(() => {
    if (!view) return { nodes: [] as PipelineNode[], edges: [] as Edge[] };

    type Spec = {
      id: string;
      title: string;
      role: string;
      state: NodeState;
      Icon: LucideIcon;
      cap?: string;
    };

    const specs: Spec[] = [
      { id: "signal", title: "Signal", role: "input", state: "fixed", Icon: ROLE_ICON.signal },
      { id: "planner", title: "Planner", role: "router", state: "fixed", Icon: ROLE_ICON.planner },
    ];

    for (const cap of view.sequence) {
      let state: NodeState = "fixed";
      if (alwaysOnCaps.has(cap)) state = "alwayson";
      else if (selectableCaps.has(cap))
        state = currentRoster.includes(cap) ? "active" : "inactive";
      specs.push({
        id: `cap_${cap}`,
        title: prettify(cap),
        role: "specialist",
        state,
        Icon: Sparkles,
        cap,
      });
    }

    specs.push({ id: "policy", title: "Policy Gate", role: "guardrail", state: "fixed", Icon: ROLE_ICON.policy });
    specs.push({ id: "hitl", title: "HITL", role: "approval", state: "fixed", Icon: ROLE_ICON.hitl });
    specs.push({ id: "commit", title: "Commit", role: "output", state: "fixed", Icon: ROLE_ICON.commit });

    const builtNodes: PipelineNode[] = specs.map((s, i) => ({
      id: s.id,
      type: "pipeline",
      position: { x: i * 230, y: 0 },
      data: {
        title: s.title,
        role: s.role,
        state: s.state,
        Icon: s.Icon,
        clickable: s.state === "active" || s.state === "inactive",
        onToggle: s.cap ? () => toggleCap(s.cap as string) : undefined,
      },
      draggable: false,
      selectable: false,
    }));

    const builtEdges: Edge[] = [];
    for (let i = 0; i < specs.length - 1; i += 1) {
      const a = specs[i];
      const b = specs[i + 1];
      // An edge touching a toggled-off specialist reads as a dormant branch.
      const muted = a.state === "inactive" || b.state === "inactive";
      const color = muted ? EDGE_MUTED : ACCENT;
      builtEdges.push({
        id: `e_${a.id}_${b.id}`,
        source: a.id,
        target: b.id,
        type: "smoothstep",
        animated: !muted,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color,
          width: 16,
          height: 16,
        },
        style: muted
          ? { stroke: color, strokeWidth: 1.5, strokeDasharray: "5 4" }
          : { stroke: color, strokeWidth: 2 },
      });
    }

    return { nodes: builtNodes, edges: builtEdges };
  }, [view, alwaysOnCaps, selectableCaps, currentRoster, toggleCap]);

  // --- Persist ------------------------------------------------------------
  const handleSave = async () => {
    if (!view) return;
    setSaving(true);
    try {
      // Only send points that differ from the base pack; omitting a point
      // reverts it to the default on the backend.
      const rosters: WorkflowRosters = {};
      for (const dp of view.decision_points) {
        const roster = edited[dp.key] ?? [];
        if (!sameSet(roster, dp.base_roster)) rosters[dp.key] = roster;
      }
      const v = await putWorkflow(domain, rosters);
      applyView(v);
      setSavedAt(true);
      toast("Workflow saved for your workspace", {
        description: "The planner now routes through these specialists.",
        variant: "success",
      });
    } catch {
      toast("Could not save workflow", {
        description: "The backend was unreachable. Try again.",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  };

  // Reset the selected decision point's roster to the base pack default. Local
  // until Save, which then reverts the override on the backend.
  const handleResetPoint = () => {
    if (!selectedDp) return;
    setSavedAt(false);
    setEdited((prev) => ({
      ...prev,
      [selectedDp.key]: [...selectedDp.base_roster],
    }));
  };

  // Reset every decision point to its default. Save then clears the whole
  // override (the diff map sent is empty).
  const handleResetAll = () => {
    if (!view) return;
    setSavedAt(false);
    setEdited((prev) => {
      const next = { ...prev };
      for (const dp of view.decision_points) next[dp.key] = [...dp.base_roster];
      return next;
    });
  };

  const domainOptions = useMemo(() => {
    if (domains.length > 0) return domains;
    const fallback = view
      ? [{ key: view.domain, display_name: view.domain_name }]
      : [{ key: domain, display_name: prettify(domain) }];
    return fallback as DomainSummary[];
  }, [domains, view, domain]);

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      {/* Theme-matched react-flow controls (grayscale, bordered, rounded). */}
      <style>{`
.react-flow__controls.workflow-controls{border:1px solid hsl(var(--border));border-radius:8px;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,0.06)}
.react-flow__controls.workflow-controls .react-flow__controls-button{background:hsl(var(--card));border-bottom:1px solid hsl(var(--border));color:hsl(var(--foreground));width:26px;height:26px}
.react-flow__controls.workflow-controls .react-flow__controls-button:hover{background:hsl(var(--secondary))}
.react-flow__controls.workflow-controls .react-flow__controls-button svg{fill:currentColor;max-width:12px;max-height:12px}
`}</style>

      <PageHeader
        eyebrow="Platform"
        title="Workflow Studio"
        description="Configure which specialists run at each decision point."
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
            <Badge variant={view?.has_override ? "success" : "muted"}>
              {view?.has_override ? "Customized" : "Base pack"}
            </Badge>
          </>
        }
      />

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-[420px] w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : error || !view ? (
        <div className="panel">
          <ErrorState
            title="Could not load the workflow"
            description="We could not reach the agent runtime. Check your connection and try again."
            onRetry={() => void load(domain)}
          />
        </div>
      ) : view.decision_points.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={Network}
            title="No decision points"
            description="This domain pack does not expose any tunable decision points yet."
          />
        </div>
      ) : (
        <div className="space-y-5">
          {/* Controls: decision point selector + its rationale and signals. */}
          <div className="panel flex flex-col gap-4 p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div className="w-full sm:max-w-xs">
                <label className="mb-1.5 block text-eyebrow">
                  Decision point
                </label>
                <Select
                  aria-label="Decision point"
                  value={selectedKey}
                  onChange={(e) => {
                    setSelectedKey(e.target.value);
                    setSavedAt(false);
                  }}
                >
                  {view.decision_points.map((dp) => (
                    <option key={dp.key} value={dp.key}>
                      {dp.label}
                    </option>
                  ))}
                </Select>
              </div>
              {selectedOverridden ? (
                <Badge variant="success" className="self-start sm:self-auto">
                  Customized
                </Badge>
              ) : null}
            </div>

            {selectedDp ? (
              <div className="space-y-2.5">
                <p className="text-sm text-muted-foreground">
                  {selectedDp.rationale}
                </p>
                {selectedDp.signals.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-eyebrow">Signals</span>
                    {selectedDp.signals.map((s) => (
                      <Badge key={s} variant="info">
                        {s}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          {/* React Flow canvas: the pipeline left to right. */}
          <div className="panel overflow-hidden p-0">
            <div className="flex flex-col gap-2 border-b border-border px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Network className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold tracking-tight">
                  Orchestration graph
                </h3>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-primary" aria-hidden />
                  Active
                </span>
                <span className="flex items-center gap-1.5">
                  <span
                    className="h-0 w-4 border-t border-dashed"
                    style={{ borderColor: EDGE_MUTED }}
                    aria-hidden
                  />
                  Inactive
                </span>
                <span className="flex items-center gap-1.5">
                  <Lock className="h-3 w-3" aria-hidden />
                  Always on
                </span>
              </div>
            </div>
            <div className="h-[420px] w-full bg-background">
              <ReactFlow
                key={domain}
                nodes={nodes}
                edges={edges}
                nodeTypes={NODE_TYPES}
                fitView
                fitViewOptions={FIT_VIEW_OPTIONS}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
                panOnScroll
                zoomOnScroll={false}
                zoomOnDoubleClick={false}
                minZoom={0.4}
                maxZoom={1.5}
                proOptions={PRO_OPTIONS}
              >
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={20}
                  size={1}
                  color="#e7e5e4"
                />
                <Controls
                  className="workflow-controls"
                  showInteractive={false}
                />
              </ReactFlow>
            </div>
          </div>

          {/* Specialist toggles for the selected point (works without precise
              node clicking). */}
          <div className="panel p-5">
            <div className="mb-3 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-muted-foreground" />
              <h3 className="text-sm font-semibold tracking-tight">
                Specialists at this decision point
              </h3>
              <Badge variant="muted">
                {currentRoster.length}/{selectable.length} active
              </Badge>
            </div>

            {selectable.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Every specialist for this domain is always on; there is nothing
                to toggle here.
              </p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {selectable.map((s) => {
                  const active = currentRoster.includes(s.capability);
                  return (
                    <button
                      key={s.capability}
                      type="button"
                      onClick={() => toggleCap(s.capability)}
                      aria-pressed={active}
                      className={cn(
                        "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors",
                        active
                          ? "border-primary/60 bg-primary/[0.04] ring-1 ring-primary/20"
                          : "border-dashed border-border bg-card opacity-70 hover:opacity-100",
                      )}
                    >
                      <MiniSwitch on={active} />
                      <span className="min-w-0">
                        <span className="flex items-center gap-1.5">
                          <span className="font-mono text-xs font-semibold tracking-tight text-foreground">
                            {prettify(s.capability)}
                          </span>
                          <span
                            className={cn(
                              "rounded-full px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide",
                              active
                                ? "bg-primary/10 text-primary ring-1 ring-inset ring-primary/25"
                                : "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
                            )}
                          >
                            {active ? "On" : "Off"}
                          </span>
                        </span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          {s.description}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {alwaysOnCaps.size > 0 ? (
              <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-border pt-4">
                <span className="text-eyebrow">Always on</span>
                {[...alwaysOnCaps].map((cap) => (
                  <Badge key={cap} variant="outline" className="gap-1">
                    <Lock className="h-2.5 w-2.5" aria-hidden />
                    {prettify(cap)}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>

          {/* Save / reset controls. */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              {dirty
                ? "You have unsaved changes."
                : savedAt
                  ? "Saved."
                  : view.has_override
                    ? "Showing your saved workspace workflow."
                    : "Showing the base pack workflow."}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {dirty || anyOverridden ? (
                <>
                  <Button
                    variant="ghost"
                    onClick={handleResetAll}
                    disabled={saving || !anyOverridden}
                    title="Revert every decision point to the base pack"
                  >
                    <RefreshCw className="mr-1.5 h-4 w-4" /> Reset all
                  </Button>
                  <Button
                    variant="outline"
                    onClick={handleResetPoint}
                    disabled={saving || !selectedOverridden}
                    title="Revert this decision point to the base pack"
                  >
                    <RotateCcw className="mr-1.5 h-4 w-4" /> Reset to defaults
                  </Button>
                </>
              ) : null}
              <Button onClick={handleSave} disabled={saving || !dirty}>
                {savedAt && !dirty ? (
                  <Check className="mr-1.5 h-4 w-4" />
                ) : (
                  <Save className="mr-1.5 h-4 w-4" />
                )}
                {saving ? "Saving..." : savedAt && !dirty ? "Saved" : "Save"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Deep-copy a rosters map so edits never mutate the loaded baseline.
function cloneRosters(
  src: Record<string, string[]>,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const k of Object.keys(src)) out[k] = [...src[k]];
  return out;
}
