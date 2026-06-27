// Typed client for the Workflow Studio.
//
// The backend exposes the agent orchestration graph for a domain (the full
// specialist sequence, the always-on specialists, the selectable roster, and
// the decision points an org can tune). GET returns the effective view (base
// pack merged with the org override); PUT persists per-decision-point rosters
// as the org override. Reads degrade to a null view when the backend is
// unreachable so the page can show an error state rather than crash. Requests
// carry credentials so they work behind an org-scoped backend.

import { API_BASE, ApiError } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

// A specialist candidate, in run order, with its catalog and usage metadata.
export interface WorkflowSpecialist {
  capability: string;
  description: string;
  always_on: boolean;
  // State keys the specialist produces.
  output_keys: string[];
  // Model cost tier: cheap | standard | strong.
  cost_tier: string;
  tags: string[];
  // Governance-tagged tools the specialist may call.
  tools: string[];
  // Decision point keys whose effective roster includes this specialist.
  used_in: string[];
}

// A decision point the planner routes through, with its effective roster.
export interface WorkflowDecisionPoint {
  key: string;
  label: string;
  signals: string[];
  base_roster: string[];
  rationale: string;
  roster: string[];
  overridden: boolean;
}

// The full effective workflow view for a domain.
export interface WorkflowView {
  domain: string;
  domain_name: string;
  sequence: string[];
  always_on: string[];
  specialists: WorkflowSpecialist[];
  decision_points: WorkflowDecisionPoint[];
  has_override: boolean;
}

// The PUT payload: a map of decision point key to its desired roster. Omitting
// a decision point (or sending an empty map) reverts it to the pack default.
export interface WorkflowRosters {
  [decisionPointKey: string]: string[];
}

/** Fetch the effective workflow view for a domain. */
export async function getWorkflow(
  domain: string,
  signal?: AbortSignal,
): Promise<WorkflowView> {
  const res = await fetch(
    `${API_BASE}/workflow/${encodeURIComponent(domain)}`,
    {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    },
  );
  if (!res.ok) {
    throw new ApiError(`GET /workflow/${domain} failed (${res.status})`, res.status);
  }
  return (await res.json()) as WorkflowView;
}

/** Persist per-decision-point rosters as the org override and return the view. */
export async function putWorkflow(
  domain: string,
  rosters: WorkflowRosters,
): Promise<WorkflowView> {
  const res = await fetch(
    `${API_BASE}/workflow/${encodeURIComponent(domain)}`,
    {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({ rosters }),
    },
  );
  if (!res.ok) {
    throw new ApiError(`PUT /workflow/${domain} failed (${res.status})`, res.status);
  }
  return (await res.json()) as WorkflowView;
}

// The assistant's response: a natural-language reply, the per-decision-point
// rosters it changed (keyed by decision point), and the full updated view it
// already persisted on the backend (so the page applies it as authoritative).
export interface WorkflowAssistantResponse {
  reply: string;
  changes: WorkflowRosters;
  view: WorkflowView;
}

/**
 * Send a natural-language instruction to the workflow assistant. The backend
 * reads the current workflow, applies the instruction, persists it, and returns
 * the updated view plus the decision points it changed. Errors surface to the
 * caller so the chat can show an honest failure rather than a silent no-op.
 */
export async function postWorkflowAssistant(
  domain: string,
  message: string,
): Promise<WorkflowAssistantResponse> {
  const res = await fetch(
    `${API_BASE}/workflow/${encodeURIComponent(domain)}/assistant`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({ message }),
    },
  );
  if (!res.ok) {
    throw new ApiError(
      `POST /workflow/${domain}/assistant failed (${res.status})`,
      res.status,
    );
  }
  return (await res.json()) as WorkflowAssistantResponse;
}
