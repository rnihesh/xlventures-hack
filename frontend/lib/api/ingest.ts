// Typed client for the live ingestion connector (workflow step 1).
//
// POST /ingest turns pasted or uploaded interaction text into citeable,
// retrievable evidence. GET /ingest/sources lists the recognized source types.
// POST /ingest/web runs an optional best-effort live web search.
//
// Reads (sources) fall back to a local list so the select renders even if the
// backend is briefly unreachable. The import mutation surfaces real errors so
// the user knows whether their evidence actually landed.

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

export interface IngestSource {
  key: string;
  label: string;
  description: string;
}

export interface IngestRequest {
  text: string;
  source_type: string;
  title?: string | null;
  account_id?: string | null;
  domain?: string;
}

export interface IngestResponse {
  ok: boolean;
  chunks_written: number;
  ids: string[];
  doc_id: string;
  account_id: string | null;
  source_type: string;
  title: string;
  domain: string;
  embed_method: string;
  persisted: string;
  detail: string;
}

export interface WebIngestRequest {
  query: string;
  account_id?: string | null;
  title?: string | null;
  domain?: string;
}

// Mirrors backend SOURCE_TYPES so the select is populated even offline.
export const DEFAULT_SOURCES: IngestSource[] = [
  { key: "meeting_notes", label: "Meeting notes", description: "Notes from a call, QBR, or internal sync." },
  { key: "call_transcript", label: "Call transcript", description: "Verbatim transcript of a customer or sales call." },
  { key: "email", label: "Email", description: "An inbound or outbound email thread." },
  { key: "support_ticket", label: "Support ticket", description: "A support or success ticket and its conversation." },
  { key: "crm_record", label: "CRM record", description: "Pasted CRM fields, account notes, or exported rows." },
  { key: "chat_message", label: "Chat message", description: "Slack, Teams, or in-app chat exchange." },
  { key: "document", label: "Document", description: "A general document, brief, or knowledge article." },
  { key: "web", label: "Web result", description: "Snippet captured from a live web search." },
];

export async function getIngestSources(
  signal?: AbortSignal,
): Promise<IngestSource[]> {
  try {
    const res = await fetch(`${API_BASE}/ingest/sources`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
    if (!res.ok) throw new Error(`GET /ingest/sources failed (${res.status})`);
    const data = (await res.json()) as { sources?: IngestSource[] };
    return data.sources && data.sources.length ? data.sources : DEFAULT_SOURCES;
  } catch {
    return DEFAULT_SOURCES;
  }
}

/** Ingest raw interaction text. Throws on failure so the UI can report it. */
export async function ingestText(
  payload: IngestRequest,
): Promise<IngestResponse> {
  const res = await fetch(`${API_BASE}/ingest`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = `Import failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* keep the status-based message */
    }
    throw new Error(detail);
  }
  return (await res.json()) as IngestResponse;
}

/**
 * Optional live web-search ingest. Best-effort: returns ok:false (rather than
 * throwing) when the network is unavailable or there are no public results.
 */
export async function ingestWeb(
  payload: WebIngestRequest,
): Promise<IngestResponse> {
  try {
    const res = await fetch(`${API_BASE}/ingest/web`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      return {
        ok: false,
        chunks_written: 0,
        ids: [],
        doc_id: "",
        account_id: payload.account_id ?? null,
        source_type: "web",
        title: payload.title ?? "",
        domain: payload.domain ?? "customer_success",
        embed_method: "none",
        persisted: "none",
        detail: `Web search failed (${res.status})`,
      };
    }
    return (await res.json()) as IngestResponse;
  } catch {
    return {
      ok: false,
      chunks_written: 0,
      ids: [],
      doc_id: "",
      account_id: payload.account_id ?? null,
      source_type: "web",
      title: payload.title ?? "",
      domain: payload.domain ?? "customer_success",
      embed_method: "none",
      persisted: "none",
      detail: "Web search unavailable (offline).",
    };
  }
}
