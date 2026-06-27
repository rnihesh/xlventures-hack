// Typed client for org-scoped contacts: the people an org reaches out to.
//
// Backs the Contacts page and the email recipient picker in the Execute panel.
// Every call sends the nba_session cookie (credentials: "include") so the
// backend resolves the caller's org, plus the optional bearer token when
// configured. Reads degrade to an empty list when the backend is unreachable so
// the picker never dead-ends; mutations surface real errors so forms can react.

import { API_BASE, ApiError } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

export interface Contact {
  id: string;
  org_id?: string;
  name: string;
  email: string;
  account_id?: string | null;
  role?: string | null;
  created_at?: string;
}

// Form payload mirroring the backend ContactIn / ContactUpdate models.
export interface ContactInput {
  name: string;
  email: string;
  account_id?: string | null;
  role?: string | null;
}

export type ContactUpdateInput = Partial<ContactInput>;

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

/** List every contact for the caller's org. Empty list when offline. */
export async function listContacts(signal?: AbortSignal): Promise<Contact[]> {
  try {
    const res = await fetch(`${API_BASE}/contacts`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
    if (!res.ok) {
      throw new ApiError(`GET /contacts failed (${res.status})`, res.status);
    }
    return (await res.json()) as Contact[];
  } catch {
    return [];
  }
}

/** List the org's contacts linked to one account. Empty list when offline. */
export async function listAccountContacts(
  accountId: string,
  signal?: AbortSignal,
): Promise<Contact[]> {
  try {
    const res = await fetch(
      `${API_BASE}/accounts/${encodeURIComponent(accountId)}/contacts`,
      {
        headers: authHeaders({ Accept: "application/json" }),
        credentials: "include",
        cache: "no-store",
        signal,
      },
    );
    if (!res.ok) {
      throw new Error(`GET account contacts failed (${res.status})`);
    }
    return (await res.json()) as Contact[];
  } catch {
    return [];
  }
}

/** Create a contact in the caller's org. */
export function createContact(payload: ContactInput): Promise<Contact> {
  return send<Contact>("/contacts", "POST", payload);
}

/** Apply a partial update to an existing contact. */
export function updateContact(
  id: string,
  payload: ContactUpdateInput,
): Promise<Contact> {
  return send<Contact>(`/contacts/${encodeURIComponent(id)}`, "PUT", payload);
}

/** Remove a contact from the caller's org. */
export function deleteContact(id: string): Promise<{ deleted: string }> {
  return send<{ deleted: string }>(
    `/contacts/${encodeURIComponent(id)}`,
    "DELETE",
  );
}
