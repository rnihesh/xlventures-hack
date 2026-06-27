// Typed client for the extensibility flow: list, validate, save, delete domains.
//
// This backs the "add a new domain in 60 seconds" panel. An org pastes a domain
// pack YAML, it is validated against the pack schema, stored as an org pack, and
// then appears in the domain dropdown so a decision can be run on it. Every
// request is scoped to the caller's org via the nba_session cookie, so all
// fetches send credentials:"include". Reads degrade gracefully so the page never
// crashes offline.

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import type { DomainSummary } from "@/lib/types";

// A compact, human readable summary of a validated pack (the validate endpoint).
export interface PackSummary {
  domain: string;
  display_name: string;
  decision_points: number;
  actions: number;
  signals: number;
  kpis: number;
  playbooks: number;
  policies: number;
  decision_point_labels: string[];
  action_titles: string[];
}

// The result of POST /domains/validate.
export interface ValidateResult {
  ok: boolean;
  errors: string[];
  summary: PackSummary | null;
}

// The result of POST /domains.
export interface SaveResult {
  ok: boolean;
  domain: string;
  summary: DomainSummary;
  created_at?: string;
  display_name?: string;
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    // Surface the backend's structured validation errors when present.
    let detail: unknown;
    try {
      detail = (await res.json())?.detail;
    } catch {
      detail = undefined;
    }
    const errors =
      detail && typeof detail === "object" && "errors" in detail
        ? (detail as { errors: string[] }).errors
        : undefined;
    const message = errors?.length
      ? errors.join("; ")
      : `${res.url} failed (${res.status})`;
    const err = new Error(message) as Error & { errors?: string[]; status?: number };
    err.errors = errors;
    err.status = res.status;
    throw err;
  }
  return (await res.json()) as T;
}

/**
 * List every domain available to the org: base packs plus this org's uploaded
 * packs. Returns an empty list when the backend is unreachable so the caller can
 * decide on a fallback.
 */
export async function getDomains(
  signal?: AbortSignal,
): Promise<DomainSummary[]> {
  try {
    const res = await fetch(`${API_BASE}/domains`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
    const data = await readJson<DomainSummary[]>(res);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

/**
 * Validate a domain pack YAML against the schema without storing it. Never
 * throws on a bad pack: the result carries ok=false plus the error messages so
 * the editor can render them inline.
 */
export async function validatePack(
  yaml: string,
  signal?: AbortSignal,
): Promise<ValidateResult> {
  try {
    const res = await fetch(`${API_BASE}/domains/validate`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({ yaml }),
      signal,
    });
    return await readJson<ValidateResult>(res);
  } catch (err) {
    const errors = (err as { errors?: string[] }).errors ?? [
      "Could not reach the validator. Check the backend is running.",
    ];
    return { ok: false, errors, summary: null };
  }
}

/**
 * Validate and save a domain pack as this org's domain. Surfaces real errors
 * (including the backend's validation messages on the thrown Error's ``errors``)
 * because saving requires the live backend.
 */
export async function savePack(yaml: string): Promise<SaveResult> {
  const res = await fetch(`${API_BASE}/domains`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ yaml }),
  });
  return readJson<SaveResult>(res);
}

/**
 * Delete one of this org's uploaded packs. Base packs cannot be deleted (the
 * backend returns 404), which surfaces as a thrown Error.
 */
export async function deletePack(domain: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/domains/${encodeURIComponent(domain)}`,
    {
      method: "DELETE",
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
    },
  );
  await readJson<{ ok: boolean }>(res);
}
