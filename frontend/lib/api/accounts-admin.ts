// Typed client for the add-accounts experience: create, update, delete an
// org-scoped account, and one-click import of the demo corpus. Every call sends
// the nba_session cookie (credentials: "include") so the backend resolves the
// caller's org, plus the optional bearer token when configured.
//
// Mutations surface real errors (unlike the read client's offline fallbacks) so
// the form can show the user what went wrong.

import { API_BASE, ApiError } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import type { Account } from "@/lib/types";

// The form payload. Mirrors the backend AccountIn model. All but `name` are
// optional; `signals` is a list of free-text labels (comma split happens in the
// UI), `notes` is ingested as retrievable evidence for the account.
export interface AccountInput {
  name: string;
  domain?: string;
  industry?: string;
  segment?: string;
  arr?: number;
  health_score?: number;
  risk_level?: string;
  owner?: string;
  renewal_date?: string;
  signals?: string[];
  notes?: string;
}

export type AccountUpdateInput = Partial<AccountInput>;

export interface ImportDemoResult {
  imported: number;
}

async function send<T>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: authHeaders(
      body === undefined
        ? { Accept: "application/json" }
        : { "Content-Type": "application/json", Accept: "application/json" },
    ),
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    throw new ApiError(`${method} ${path} failed (${res.status})`, res.status);
  }
  return (await res.json()) as T;
}

/** Create an account in the caller's org. Resolves to its inbox summary. */
export function createAccount(payload: AccountInput): Promise<Account> {
  return send<Account>("/accounts", "POST", payload);
}

/** Apply a partial update to an existing account. */
export function updateAccount(
  id: string,
  payload: AccountUpdateInput,
): Promise<Account> {
  return send<Account>(`/accounts/${encodeURIComponent(id)}`, "PUT", payload);
}

/** Remove an account from the caller's org. */
export function deleteAccount(id: string): Promise<{ deleted: string }> {
  return send<{ deleted: string }>(
    `/accounts/${encodeURIComponent(id)}`,
    "DELETE",
  );
}

/** Copy the seeded demo accounts into the caller's org (idempotent). */
export function importDemoAccounts(): Promise<ImportDemoResult> {
  return send<ImportDemoResult>("/accounts/import-demo", "POST");
}
