// Typed client for configurable business rules (per-org pack overrides).
//
// Backs the Rules editor. A domain pack ships with base policy rules and an
// action catalog; an org tailors them here and the edits are stored as an
// override and merged back on read. Every request is scoped to the caller's org
// via the nba_session cookie, so all fetches send credentials:"include". Reads
// degrade to an empty view when the backend is unreachable so the page never
// crashes offline.

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

export type RuleSeverity = "low" | "medium" | "high" | string;

// A declarative policy rule as authored in a pack or an org override.
export interface RulePolicy {
  id: string;
  description: string;
  type: string;
  condition: Record<string, unknown>;
  severity: RuleSeverity;
  requires_approval: boolean;
}

// An eligible play the recommender may propose.
export interface RuleAction {
  key: string;
  title: string;
  description: string;
  eligibility?: string;
}

// The effective merged view returned by GET /rules/{domain}.
export interface RulesView {
  domain: string;
  display_name: string;
  policies: RulePolicy[];
  actions: RuleAction[];
  has_override: boolean;
}

// The override payload sent to PUT /rules/{domain}. Omitting a section leaves
// the base pack's section untouched; sending an empty body clears the override.
export interface RulesPayload {
  policies?: RulePolicy[];
  actions?: RuleAction[];
}

const EMPTY_VIEW = (domain: string): RulesView => ({
  domain,
  display_name: domain,
  policies: [],
  actions: [],
  has_override: false,
});

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.url} failed (${res.status})`);
  return (await res.json()) as T;
}

/**
 * Fetch a domain's effective rules (base pack merged with the org override).
 * Returns an empty view when the backend is unreachable so the editor still
 * renders rather than blanking out.
 */
export async function getRules(
  domain: string,
  signal?: AbortSignal,
): Promise<RulesView> {
  try {
    const res = await fetch(`${API_BASE}/rules/${encodeURIComponent(domain)}`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
    const data = await readJson<Partial<RulesView>>(res);
    return {
      domain: data.domain ?? domain,
      display_name: data.display_name ?? domain,
      policies: data.policies ?? [],
      actions: data.actions ?? [],
      has_override: data.has_override ?? false,
    };
  } catch {
    return EMPTY_VIEW(domain);
  }
}

/**
 * Save the org's override for a domain. Sending the full desired lists (the
 * editor derives them from the effective view) supports add, edit, and remove.
 * Returns the new effective view. Surfaces real errors to the caller.
 */
export async function saveRules(
  domain: string,
  payload: RulesPayload,
): Promise<RulesView> {
  const res = await fetch(`${API_BASE}/rules/${encodeURIComponent(domain)}`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return readJson<RulesView>(res);
}
