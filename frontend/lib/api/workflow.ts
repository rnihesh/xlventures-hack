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

// A selectable specialist candidate, in run order.
export interface WorkflowSpecialist {
  capability: string;
  description: string;
  always_on: boolean;
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
