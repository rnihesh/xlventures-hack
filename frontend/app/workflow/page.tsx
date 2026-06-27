"use client";

// Visual Workflow Studio.
//
// Renders the agent orchestration graph for a domain top to bottom and lets an
// org tune which selectable specialists run at each decision point three ways:
// clicking the On/Off switch on a node, the specialist chips, or a natural
// language assistant. The planner always runs the always-on specialists; the
// selectable ones are toggled per decision point. Manual edits are local until
// Save (PUT rosters, only the points that differ from base); the assistant
// persists on the backend and returns an authoritative view the page applies
// live. Fully offline-safe: with no backend the view shows an error state and
// Save / assistant surface real errors rather than crashing.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
  X,
  Send,
  Wand2,
  Wrench,
  Boxes,
  MapPin,
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
  postWorkflowAssistant,
  type WorkflowView,
  type WorkflowSpecialist,
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

function costVariant(tier: string): "muted" | "secondary" | "warning" {
  if (tier === "strong") return "warning";
  if (tier === "cheap") return "muted";
  return "secondary";
}

// --------------------------------------------------------------------------
// Custom node
// --------------------------------------------------------------------------

type NodeState = "fixed" | "active" | "inactive" | "alwayson";

type PipelineNodeData = {
  title: string;
  role: string;
  state: NodeState;
  selectable: boolean;
  Icon: LucideIcon;
  onOpenDetail: () => void;
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
  const { title, role, state, selectable, Icon, onOpenDetail, onToggle } = data;
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
      onClick={onOpenDetail}
      role="button"
      title="Click for details"
      className={cn(
        "relative w-[184px] cursor-pointer select-none rounded-xl border py-2.5 pl-3 pr-2.5 shadow-sm transition-colors hover:border-primary/70",
        cardTone,
      )}
    >
      {isActive ? (
        <span
          className="absolute inset-x-2 top-0 h-1 rounded-b bg-primary"
          aria-hidden
        />
      ) : null}

      <Handle
        type="target"
        position={Position.Top}
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
        {selectable ? (
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
        {selectable ? (
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
        position={Position.Bottom}
        className="!h-1.5 !w-1.5 !border-0 !bg-border"
      />
    </div>
  );
}

const NODE_TYPES = { pipeline: PipelineNodeView };

// Module-scope to keep object identity stable across renders.
const PRO_OPTIONS = { hideAttribution: true };
const FIT_VIEW_OPTIONS = { padding: 0.14 };
const ROLE_ICON: Record<string, LucideIcon> = {
  signal: Radio,
  planner: Route,
  policy: ShieldCheck,
  hitl: UserCheck,
  commit: Flag,
};

const EXAMPLE_PROMPTS = [
  "Remove outcome simulator from renewal risk",
  "Only risk scorer and play recommender for health drop",
  "Reset all to defaults",
];

// A node the detail sheet describes.
type SelectedNode = {
  title: string;
  role: string;
  Icon: LucideIcon;
  kind: "specialist" | "orchestration";
  state: NodeState;
  cap?: string;
};

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  changed?: string[]; // decision point labels changed by this turn
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

  // Detail sheet + assistant chat.
  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [changedKeys, setChangedKeys] = useState<string[]>([]);
  const [pulseTick, setPulseTick] = useState(0);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const msgId = useRef(0);

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
    setMessages([]);
    setSelectedNode(null);
    setChangedKeys([]);
    void load(domain, ctrl.signal);
    return () => ctrl.abort();
  }, [domain, load]);

  // Keep the chat thread pinned to the latest message.
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

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

  // capability -> specialist, and decision point key -> label, for the sheet.
  const specByCap = useMemo(() => {
    const m = new Map<string, WorkflowSpecialist>();
    for (const s of view?.specialists ?? []) m.set(s.capability, s);
    return m;
  }, [view]);
  const dpLabel = useMemo(() => {
    const m = new Map<string, string>();
    for (const dp of view?.decision_points ?? []) m.set(dp.key, dp.label);
    return m;
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

  // --- Graph model (top to bottom) ----------------------------------------
  const { nodes, edges } = useMemo(() => {
    if (!view) return { nodes: [] as PipelineNode[], edges: [] as Edge[] };

    type Spec = {
      id: string;
      title: string;
      role: string;
      state: NodeState;
      Icon: LucideIcon;
      kind: "specialist" | "orchestration";
      cap?: string;
    };

    const specs: Spec[] = [
      { id: "signal", title: "Signal", role: "input", state: "fixed", Icon: ROLE_ICON.signal, kind: "orchestration" },
      { id: "planner", title: "Planner", role: "router", state: "fixed", Icon: ROLE_ICON.planner, kind: "orchestration" },
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
        kind: "specialist",
        cap,
      });
    }

    specs.push({ id: "policy", title: "Policy Gate", role: "guardrail", state: "fixed", Icon: ROLE_ICON.policy, kind: "orchestration" });
    specs.push({ id: "hitl", title: "HITL", role: "approval", state: "fixed", Icon: ROLE_ICON.hitl, kind: "orchestration" });
    specs.push({ id: "commit", title: "Commit", role: "output", state: "fixed", Icon: ROLE_ICON.commit, kind: "orchestration" });

    const builtNodes: PipelineNode[] = specs.map((s, i) => ({
      id: s.id,
      type: "pipeline",
      position: { x: 0, y: i * 116 },
      data: {
        title: s.title,
        role: s.role,
        state: s.state,
        Icon: s.Icon,
        selectable: s.state === "active" || s.state === "inactive",
        onOpenDetail: () =>
          setSelectedNode({
            title: s.title,
            role: s.role,
            Icon: s.Icon,
            kind: s.kind,
            state: s.state,
            cap: s.cap,
          }),
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

  // --- Persist (manual) ---------------------------------------------------
  const handleSave = async () => {
    if (!view) return;
    setSaving(true);
    try {
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

  const handleResetPoint = () => {
    if (!selectedDp) return;
    setSavedAt(false);
    setEdited((prev) => ({
      ...prev,
      [selectedDp.key]: [...selectedDp.base_roster],
    }));
  };

  const handleResetAll = () => {
    if (!view) return;
    setSavedAt(false);
    setEdited((prev) => {
      const next = { ...prev };
      for (const dp of view.decision_points) next[dp.key] = [...dp.base_roster];
      return next;
    });
  };

  // --- Assistant ----------------------------------------------------------
  const sendMessage = async (text: string) => {
    const message = text.trim();
    if (!message || sending) return;
    setChatInput("");
    setMessages((prev) => [
      ...prev,
      { id: (msgId.current += 1), role: "user", content: message },
    ]);
    setSending(true);
    try {
      const res = await postWorkflowAssistant(domain, message);
      // The backend already persisted; the returned view is authoritative.
      applyView(res.view);
      const keys = Object.keys(res.changes ?? {});
      const labels = keys.map((k) => {
        const dp = res.view.decision_points.find((d) => d.key === k);
        return dp?.label ?? prettify(k);
      });
      setMessages((prev) => [
        ...prev,
        {
          id: (msgId.current += 1),
          role: "assistant",
          content: res.reply,
          changed: labels,
        },
      ]);
      setSavedAt(false);
      if (keys.length > 0) {
        setChangedKeys(keys);
        setPulseTick((t) => t + 1);
        setSelectedKey(keys[0]);
        window.setTimeout(() => setChangedKeys([]), 2600);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: (msgId.current += 1),
          role: "assistant",
          content:
            "I could not reach the workflow assistant just now. Check the connection and try again.",
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  const domainOptions = useMemo(() => {
    if (domains.length > 0) return domains;
    const fallback = view
      ? [{ key: view.domain, display_name: view.domain_name }]
      : [{ key: domain, display_name: prettify(domain) }];
    return fallback as DomainSummary[];
  }, [domains, view, domain]);

  const detailSpec =
    selectedNode?.cap != null ? specByCap.get(selectedNode.cap) ?? null : null;

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      {/* Theme-matched react-flow controls + a soft "changed" pulse. */}
      <style>{`
.react-flow__controls.workflow-controls{border:1px solid hsl(var(--border));border-radius:8px;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,0.06)}
.react-flow__controls.workflow-controls .react-flow__controls-button{background:hsl(var(--card));border-bottom:1px solid hsl(var(--border));color:hsl(var(--foreground));width:26px;height:26px}
.react-flow__controls.workflow-controls .react-flow__controls-button:hover{background:hsl(var(--secondary))}
.react-flow__controls.workflow-controls .react-flow__controls-button svg{fill:currentColor;max-width:12px;max-height:12px}
@keyframes wfPulse{0%{box-shadow:0 0 0 0 rgba(217,119,87,0.40)}70%{box-shadow:0 0 0 7px rgba(217,119,87,0)}100%{box-shadow:0 0 0 0 rgba(217,119,87,0)}}
.wf-pulse{animation:wfPulse 1.3s ease-out 2}
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
          <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
            <Skeleton className="h-[560px] w-full" />
            <Skeleton className="h-[560px] w-full" />
          </div>
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
          {/* Decision point selector + its rationale and signals. */}
          <div
            key={pulseTick}
            className={cn(
              "panel flex flex-col gap-4 rounded-xl p-5",
              changedKeys.length > 0 && "wf-pulse",
            )}
          >
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
              <div className="flex items-center gap-2">
                {selectedKey && changedKeys.includes(selectedKey) ? (
                  <Badge variant="warning" className="animate-pulse">
                    <Wand2 className="h-3 w-3" /> Updated
                  </Badge>
                ) : null}
                {selectedOverridden ? (
                  <Badge variant="success">Customized</Badge>
                ) : null}
              </div>
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

          {/* Two columns on desktop: graph + assistant chat. */}
          <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
            {/* Vertical orchestration graph. */}
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
              <div className="h-[460px] w-full bg-background lg:h-[560px]">
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
                  minZoom={0.3}
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

            {/* Assistant chat. */}
            <div className="panel flex h-[460px] flex-col overflow-hidden p-0 lg:h-[560px]">
              <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Wand2 className="h-4 w-4" />
                </span>
                <div className="leading-tight">
                  <div className="text-sm font-semibold tracking-tight">
                    Workflow assistant
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    Edit the graph in plain language
                  </div>
                </div>
              </div>

              <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4 scroll-thin">
                {messages.length === 0 ? (
                  <div className="space-y-3">
                    <p className="text-sm text-muted-foreground">
                      Ask the assistant to change which specialists run. It
                      updates the graph live and saves to your workspace.
                    </p>
                    <div className="flex flex-col gap-1.5">
                      {EXAMPLE_PROMPTS.map((p) => (
                        <button
                          key={p}
                          type="button"
                          onClick={() => void sendMessage(p)}
                          disabled={sending}
                          className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-left text-xs text-foreground transition-colors hover:border-primary/60 hover:bg-primary/[0.04] disabled:opacity-50"
                        >
                          <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" />
                          {p}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  messages.map((m) => (
                    <div
                      key={m.id}
                      className={cn(
                        "flex",
                        m.role === "user" ? "justify-end" : "justify-start",
                      )}
                    >
                      <div
                        className={cn(
                          "max-w-[85%] rounded-2xl px-3 py-2 text-sm",
                          m.role === "user"
                            ? "bg-primary text-primary-foreground"
                            : "border border-border bg-card text-foreground",
                        )}
                      >
                        <p className="whitespace-pre-wrap">{m.content}</p>
                        {m.changed && m.changed.length > 0 ? (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {m.changed.map((label) => (
                              <Badge key={label} variant="warning">
                                <Wand2 className="h-3 w-3" /> {label}
                              </Badge>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ))
                )}

                {sending ? (
                  <div className="flex justify-start">
                    <div className="flex items-center gap-1.5 rounded-2xl border border-border bg-card px-3 py-2.5">
                      <Dot /> <Dot delay="0.15s" /> <Dot delay="0.3s" />
                    </div>
                  </div>
                ) : null}
                <div ref={threadEndRef} />
              </div>

              {messages.length > 0 ? (
                <div className="flex flex-wrap gap-1.5 border-t border-border px-4 pt-3">
                  {EXAMPLE_PROMPTS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => void sendMessage(p)}
                      disabled={sending}
                      className="rounded-full border border-border bg-card px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/60 hover:text-foreground disabled:opacity-50"
                    >
                      {p}
                    </button>
                  ))}
                </div>
              ) : null}

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void sendMessage(chatInput);
                }}
                className="flex items-center gap-2 border-t border-border p-3"
              >
                <input
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  disabled={sending}
                  placeholder="Ask to change the workflow..."
                  aria-label="Message the workflow assistant"
                  className="h-10 flex-1 rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:opacity-50"
                />
                <Button
                  type="submit"
                  size="icon"
                  disabled={sending || !chatInput.trim()}
                  aria-label="Send"
                >
                  <Send className="h-4 w-4" />
                </Button>
              </form>
            </div>
          </div>

          {/* Specialist toggles for the selected point (large click targets). */}
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

      {/* Node detail sheet (overlays from the right). */}
      {selectedNode ? (
        <NodeDetailSheet
          node={selectedNode}
          spec={detailSpec}
          dpLabel={dpLabel}
          onClose={() => setSelectedNode(null)}
        />
      ) : null}
    </div>
  );
}

// A single animated typing dot.
function Dot({ delay = "0s" }: { delay?: string }) {
  return (
    <span
      className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground"
      style={{ animationDelay: delay }}
      aria-hidden
    />
  );
}

// --------------------------------------------------------------------------
// Node detail sheet
// --------------------------------------------------------------------------

function ChipRow({ items }: { items: string[] }) {
  if (items.length === 0)
    return <span className="text-xs text-muted-foreground">none</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it) => (
        <code
          key={it}
          className="rounded-md border border-border bg-background/70 px-2 py-0.5 font-mono text-xs text-foreground"
        >
          {it}
        </code>
      ))}
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-eyebrow">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {title}
      </div>
      {children}
    </div>
  );
}

function NodeDetailSheet({
  node,
  spec,
  dpLabel,
  onClose,
}: {
  node: SelectedNode;
  spec: WorkflowSpecialist | null;
  dpLabel: Map<string, string>;
  onClose: () => void;
}) {
  const Icon = node.Icon;
  const usedIn = spec?.used_in ?? [];

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-foreground/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-label={`${node.title} details`}
        className="absolute inset-y-0 right-0 flex w-full max-w-sm flex-col border-l border-border bg-card shadow-xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border p-5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
              <Icon className="h-[18px] w-[18px]" />
            </span>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight">
                {node.title}
              </div>
              <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                {node.role}
              </div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close details"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-5 scroll-thin">
          {node.kind === "orchestration" ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                A fixed orchestration step. It always runs and is not part of any
                tunable roster.
              </p>
              <Badge variant="outline" className="gap-1">
                <Lock className="h-2.5 w-2.5" aria-hidden /> fixed
              </Badge>
            </div>
          ) : !spec ? (
            <p className="text-sm text-muted-foreground">
              No catalog metadata is available for this specialist.
            </p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">{spec.description}</p>

              <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant={costVariant(spec.cost_tier)} className="capitalize">
                  {spec.cost_tier} cost
                </Badge>
                {spec.always_on ? (
                  <Badge variant="outline" className="gap-1">
                    <Lock className="h-2.5 w-2.5" aria-hidden /> always on
                  </Badge>
                ) : (
                  <Badge variant={node.state === "active" ? "success" : "muted"}>
                    {node.state === "active" ? "On here" : "Off here"}
                  </Badge>
                )}
                {spec.tags.map((t) => (
                  <Badge key={t} variant="info" className="capitalize">
                    {t}
                  </Badge>
                ))}
              </div>

              <Section icon={Wrench} title="Tools">
                <ChipRow items={spec.tools} />
              </Section>

              <Section icon={Boxes} title="Produces">
                <ChipRow items={spec.output_keys} />
              </Section>

              <Section icon={MapPin} title={`Used in (${usedIn.length})`}>
                {usedIn.length === 0 ? (
                  <span className="text-xs text-muted-foreground">
                    Not active in any decision point right now.
                  </span>
                ) : (
                  <ul className="space-y-1">
                    {usedIn.map((k) => (
                      <li
                        key={k}
                        className="flex items-center gap-2 rounded-md border border-border bg-background/70 px-2.5 py-1.5 text-xs text-foreground"
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden />
                        {dpLabel.get(k) ?? prettify(k)}
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </>
          )}
        </div>
      </aside>
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
