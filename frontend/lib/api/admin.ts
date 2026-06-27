// Typed client for the admin panel endpoints. Every call requires an
// authenticated ADMIN session: the backend returns 403 for non-admins, which
// surfaces here as an ApiError the page renders as a "not authorized" state.
//
// Reuses the same transport contract as lib/api.ts: API_BASE for the base URL,
// authHeaders for the optional bearer token, and credentials:"include" so the
// httpOnly session cookie rides along. No fallback: admin views must reflect
// the real backend response (including auth failures), never a fabricated one.

import { API_BASE, ApiError } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

export interface AdminUsage {
  events: number;
  total_tokens: number;
  cost_usd: number;
}

export interface AdminOverview {
  orgs: number;
  users: number;
  accounts: number;
  runs: number;
  usage: AdminUsage;
  usage_all_time: AdminUsage;
  days: number;
}

export interface AdminOrg {
  id: string;
  name: string;
  created_at: string;
  users: number;
  accounts: number;
  runs: number;
  last_run: string | null;
  total_tokens: number;
  cost_usd: number;
}

export interface AdminUser {
  id: string;
  email: string;
  name: string | null;
  org_id: string;
  org_name: string | null;
  role: string;
  email_verified: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AdminUsageTotals {
  events: number;
  total_tokens: number;
  cost_usd: number;
}

export interface AdminUsageByOrg {
  org_id: string;
  org_name: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  events: number;
  last_used: string | null;
}

export interface AdminUsageByModel {
  model: string;
  kind: string;
  total_tokens: number;
  cost_usd: number;
  events: number;
}

export interface AdminUsageDaily {
  day: string;
  total_tokens: number;
  cost_usd: number;
}

export interface AdminUsageReport {
  days: number;
  totals: AdminUsageTotals;
  by_org: AdminUsageByOrg[];
  by_model: AdminUsageByModel[];
  daily: AdminUsageDaily[];
}

// Bare GET that always surfaces a non-2xx as an ApiError (status carried
// through), so the page can distinguish a 403 (not authorized) from other
// failures. Mirrors the getJson transport in lib/api.ts without its fallback.
async function adminGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders({ Accept: "application/json" }),
    credentials: "include",
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    throw new ApiError(`GET ${path} failed (${res.status})`, res.status);
  }
  return (await res.json()) as T;
}

export function getAdminOverview(
  days = 30,
  signal?: AbortSignal,
): Promise<AdminOverview> {
  return adminGet<AdminOverview>(`/admin/overview?days=${days}`, signal);
}

export function getAdminOrgs(signal?: AbortSignal): Promise<AdminOrg[]> {
  return adminGet<AdminOrg[]>("/admin/orgs", signal);
}

export function getAdminUsers(signal?: AbortSignal): Promise<AdminUser[]> {
  return adminGet<AdminUser[]>("/admin/users", signal);
}

export function getAdminUsage(
  days = 30,
  signal?: AbortSignal,
): Promise<AdminUsageReport> {
  return adminGet<AdminUsageReport>(`/admin/usage?days=${days}`, signal);
}
