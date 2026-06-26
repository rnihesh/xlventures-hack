// Typed client for per-org integration connectors.
//
// Backs the Settings page. Every connector (SES email, Slack, Google) is
// scoped to the caller's org via the nba_session cookie, so all requests send
// credentials:"include". Reads degrade to an empty, "not configured" view when
// the backend is unreachable so the page never crashes offline.

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

// The connector kinds the backend understands. CRM is a forward-looking stub
// the UI renders as "coming soon"; the backend may not persist it yet.
export type ConnectorKind = "ses" | "slack" | "google" | "crm";

// A connector's stored status. "connected" means usable config is present;
// "not_configured" is the graceful offline / unset default.
export type ConnectorStatus =
  | "connected"
  | "not_configured"
  | "error"
  | string;

// Free-form config per kind (jsonb on the backend). Secrets like Google tokens
// are never sent to the client; the backend returns only safe display fields.
export interface ConnectorConfig {
  // ses
  sender_email?: string;
  // slack
  webhook_url?: string;
  // google (display only; tokens stay server-side)
  email?: string;
  expiry?: string | null;
  [key: string]: unknown;
}

export interface Connector {
  kind: ConnectorKind;
  config: ConnectorConfig;
  status: ConnectorStatus;
  updated_at?: string | null;
}

export interface GoogleStartResponse {
  // The Google consent URL to open. Empty when OAuth env is not configured.
  url: string;
  configured: boolean;
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.url} failed (${res.status})`);
  return (await res.json()) as T;
}

/**
 * List the org's connectors and their live status. Returns an empty array when
 * the backend is unreachable so the page renders every card as "not
 * configured" rather than blanking out.
 */
export async function listIntegrations(
  signal?: AbortSignal,
): Promise<Connector[]> {
  try {
    const res = await fetch(`${API_BASE}/integrations`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
    const data = await readJson<{ connectors?: Connector[] } | Connector[]>(
      res,
    );
    if (Array.isArray(data)) return data;
    return data.connectors ?? [];
  } catch {
    return [];
  }
}

/** Save (upsert) a connector's config. Surfaces real errors to the caller. */
export async function saveIntegration(
  kind: ConnectorKind,
  config: ConnectorConfig,
): Promise<Connector> {
  const res = await fetch(
    `${API_BASE}/integrations/${encodeURIComponent(kind)}`,
    {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({ config }),
    },
  );
  return readJson<Connector>(res);
}

/** Remove a connector (disconnect). Surfaces real errors to the caller. */
export async function deleteIntegration(kind: ConnectorKind): Promise<void> {
  const res = await fetch(
    `${API_BASE}/integrations/${encodeURIComponent(kind)}`,
    {
      method: "DELETE",
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
    },
  );
  if (!res.ok && res.status !== 404) {
    throw new Error(`DELETE /integrations/${kind} failed (${res.status})`);
  }
}

/**
 * Begin the Google OAuth flow: ask the backend for the consent URL built from
 * GOOGLE_CLIENT_ID + GOOGLE_REDIRECT_URI. Returns configured:false (and an
 * empty url) when OAuth env is absent so the UI can show a graceful note.
 */
export async function googleStart(): Promise<GoogleStartResponse> {
  try {
    const res = await fetch(`${API_BASE}/integrations/google/start`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
    });
    const data = await readJson<{ url?: string; configured?: boolean }>(res);
    const url = data.url ?? "";
    return { url, configured: data.configured ?? url.length > 0 };
  } catch {
    return { url: "", configured: false };
  }
}

/**
 * Exchange a Google OAuth authorization code for tokens. The backend stores the
 * tokens on the org's google connector and returns the updated connector.
 */
export async function googleExchange(code: string): Promise<Connector> {
  const res = await fetch(`${API_BASE}/integrations/google/exchange`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ code }),
  });
  return readJson<Connector>(res);
}

// Post a real test message to the org's saved Slack webhook.
export async function testSlack(): Promise<{ sent: boolean; reason?: string }> {
  try {
    const res = await fetch(`${API_BASE}/integrations/slack/test`, {
      method: "POST",
      headers: authHeaders(),
      credentials: "include",
    });
    if (!res.ok) {
      let reason = "slack_error";
      try {
        const body = (await res.json()) as { detail?: string };
        if (body.detail) reason = body.detail;
      } catch {
        /* keep default */
      }
      return { sent: false, reason };
    }
    return (await res.json()) as { sent: boolean; reason?: string };
  } catch {
    return { sent: false, reason: "unreachable" };
  }
}
