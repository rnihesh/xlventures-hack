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

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  ReactFlow,
  Background,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Network,
  Save,
  RotateCcw,
  Check,
  CircleDot,
  Lock,
} from "lucide-react";

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

type PipelineNodeData = {
  title: string;
  role: string;
  state: "fixed" | "active" | "inactive" | "alwayson";
  clickable: boolean;
  onToggle?: () => void;
};

type PipelineNode = Node<PipelineNodeData, "pipeline">;

function PipelineNodeView({ data }: NodeProps<PipelineNode>) {
  const { title, role, state, clickable, onToggle } = data;

  const tone =
    state === "active"
      ? "border-primary/60 bg-card ring-1 ring-primary/25"
      : state === "inactive"
        ? "border-dashed border-border bg-card opacity-40"
        : state === "alwayson"
          ? "border-border bg-secondary"
          : "border-border bg-card";

  return (
    <div
      onClick={clickable ? onToggle : undefined}
      role={clickable ? "button" : undefined}
      aria-pressed={clickable ? state === "active" : undefined}
      title={
        clickable
          ? state === "active"
            ? `Click to remove ${title}`
            : `Click to add ${title}`
          : undefined
      }
      className={[
        "w-[148px] select-none rounded-lg border px-3 py-2 text-center shadow-sm transition-colors",
        tone,
        clickable ? "cursor-pointer hover:border-primary/70" : "cursor-default",
      ].join(" ")}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-1.5 !w-1.5 !border-0 !bg-border"
      />
      <div className="flex items-center justify-center gap-1.5">
        {state === "active" ? (
          <CircleDot className="h-3 w-3 shrink-0 text-primary" aria-hidden />
        ) : null}
        <span className="truncate text-[13px] font-semibold tracking-tight text-foreground">
          {title}
        </span>
      </div>
      <div className="mt-0.5 flex items-center justify-center gap-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        {state === "alwayson" ? (
          <>
            <Lock className="h-2.5 w-2.5" aria-hidden />
            <span>always on</span>
          </>
        ) : (
          <span>{role}</span>
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

// Module-scope to satisfy the "no new object identity each render" guidance.
const PRO_OPTIONS = { hideAttribution: true };
const FIT_VIEW_OPTIONS = { padding: 0.18 };
const EDGE_STYLE = { stroke: "hsl(var(--border))", strokeWidth: 1.5 };

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
    setEdited(structuredCloneRosters(rosters));
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

  // The selectable specialist capabilities (the toggle candidates), in order.
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
  const selectedBase = selectedDp?.base_roster ?? [];

  // A decision point is overridden in the edited state if its roster differs
  // from the base pack default.
  const isOverridden = useCallback(
    (key: string, base: string[]) => !sameSet(edited[key] ?? [], base),
    [edited],
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
      state: PipelineNodeData["state"];
      cap?: string;
    };

    const specs: Spec[] = [
      { id: "signal", title: "Signal", role: "input", state: "fixed" },
      { id: "planner", title: "Planner", role: "router", state: "fixed" },
    ];

    for (const cap of view.sequence) {
      if (alwaysOnCaps.has(cap)) {
        specs.push({
          id: `cap_${cap}`,
          title: prettify(cap),
          role: "specialist",
          state: "alwayson",
          cap,
        });
      } else if (selectableCaps.has(cap)) {
        specs.push({
          id: `cap_${cap}`,
          title: prettify(cap),
          role: "specialist",
          state: currentRoster.includes(cap) ? "active" : "inactive",
          cap,
        });
      } else {
        specs.push({
          id: `cap_${cap}`,
          title: prettify(cap),
          role: "specialist",
          state: "fixed",
          cap,
        });
      }
    }

    specs.push({ id: "policy", title: "Policy Gate", role: "guardrail", state: "fixed" });
    specs.push({ id: "hitl", title: "HITL", role: "approval", state: "fixed" });
    specs.push({ id: "commit", title: "Commit", role: "output", state: "fixed" });

    const builtNodes: PipelineNode[] = specs.map((s, i) => ({
      id: s.id,
      type: "pipeline",
      position: { x: i * 196, y: 0 },
      data: {
        title: s.title,
        role: s.role,
        state: s.state,
        clickable: s.state === "active" || s.state === "inactive",
        onToggle: s.cap ? () => toggleCap(s.cap as string) : undefined,
      },
      draggable: false,
      selectable: false,
    }));

    const builtEdges: Edge[] = [];
    for (let i = 0; i < specs.length - 1; i += 1) {
      builtEdges.push({
        id: `e_${specs[i].id}_${specs[i + 1].id}`,
        source: specs[i].id,
        target: specs[i + 1].id,
        type: "smoothstep",
        style: EDGE_STYLE,
      });
    }

    return { nodes: builtNodes, edges: builtEdges };
  }, [view, alwaysOnCaps, selectableCaps, currentRoster, toggleCap]);

  // --- Persist ------------------------------------------------------------
  const handleSave = async () => {
    if (!view) return;
    setSaving(true);
    try {
      // Only send the points that differ from the base pack; omitting a point
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

  // Reset the selected decision point's roster to the base pack default. The
  // change is local until Save, which then reverts the override on the backend.
  const handleResetPoint = () => {
    if (!selectedDp) return;
    setSavedAt(false);
    setEdited((prev) => ({ ...prev, [selectedDp.key]: [...selectedDp.base_roster] }));
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
          <Skeleton className="h-[400px] w-full" />
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
              {selectedDp && isOverridden(selectedDp.key, selectedDp.base_roster) ? (
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
            <div className="h-[400px] w-full">
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
                <Background gap={18} color="hsl(var(--border))" />
              </ReactFlow>
            </div>
          </div>

          {/* Specialist toggles for the selected point (works without clicking
              the graph nodes precisely). */}
          <div className="panel p-5">
            <div className="mb-3 flex items-center gap-2">
              <Network className="h-4 w-4 text-muted-foreground" />
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
                      className={[
                        "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors",
                        active
                          ? "border-primary/60 bg-primary/[0.04] ring-1 ring-primary/20"
                          : "border-border bg-card opacity-70 hover:opacity-100",
                      ].join(" ")}
                    >
                      <span
                        className={[
                          "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                          active
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border text-transparent",
                        ].join(" ")}
                        aria-hidden
                      >
                        <Check className="h-3 w-3" />
                      </span>
                      <span className="min-w-0">
                        <span className="block font-mono text-xs font-semibold tracking-tight text-foreground">
                          {prettify(s.capability)}
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

            {/* Always-on context: not toggleable, shown for completeness. */}
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
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                onClick={handleResetPoint}
                disabled={
                  saving ||
                  !selectedDp ||
                  !isOverridden(selectedDp.key, selectedDp.base_roster)
                }
              >
                <RotateCcw className="mr-1.5 h-4 w-4" /> Reset to default
              </Button>
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
function structuredCloneRosters(
  src: Record<string, string[]>,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const k of Object.keys(src)) out[k] = [...src[k]];
  return out;
}
