// Typed client for the reusable agent + tool catalog.
//
// Backs the "Agents and Tools" page. The backend exposes two registries: the
// agent registry (specialists registered under a capability, looked up by the
// planner at runtime) and the tool registry (callables tagged with governance
// metadata). Both are read-only and offline-safe, so these reads degrade to an
// empty list when the backend is unreachable and the page still renders.
// Requests carry credentials so they work behind an org-scoped backend.

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

// A serialized AgentCard: everything the planner needs minus the node callable.
export interface AgentCard {
  name: string;
  capability: string;
  description: string;
  output_keys: string[];
  cost_tier: string; // cheap | standard | strong
  tags: string[];
}

// A serialized ToolSpec: a callable with its governance metadata.
export interface ToolSpec {
  name: string;
  kind: string; // python | http | mcp
  description: string;
  side_effecting: boolean;
  risk_tier: string; // low | medium | high
  binding: Record<string, unknown>;
}

async function readList<T>(path: string, signal?: AbortSignal): Promise<T[]> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
    if (!res.ok) throw new Error(`${path} failed (${res.status})`);
    const data = await res.json();
    return Array.isArray(data) ? (data as T[]) : [];
  } catch {
    return [];
  }
}

/** Fetch the agent registry (specialist capability cards). */
export function getAgents(signal?: AbortSignal): Promise<AgentCard[]> {
  return readList<AgentCard>("/agents", signal);
}

/** Fetch the tool registry (governance-tagged callables). */
export function getTools(signal?: AbortSignal): Promise<ToolSpec[]> {
  return readList<ToolSpec>("/tools", signal);
}
