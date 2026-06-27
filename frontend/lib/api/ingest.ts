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

// A deterministically extracted candidate signal (offline, no LLM): a sentence
// that mentions churn / renewal / usage / sentiment, tagged with its category.
export interface ExtractedSignal {
  category: string;
  label: string;
  keyword: string;
  text: string;
}

export interface IngestResponse {
  ok: boolean;
  chunks_written: number;
  ids: string[];
  doc_id: string;
  id: string;
  account_id: string | null;
  source_type: string;
  title: string;
  domain: string;
  embed_method: string;
  persisted: string;
  detail: string;
  extracted_signals: ExtractedSignal[];
  chars: number;
  duplicate?: boolean;
  ts?: number;
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

// Realistic example text per source type, so a user can try the experience in
// one click. Keyed by source key; falls back to EXAMPLE_FALLBACK.
export const EXAMPLE_FALLBACK =
  "QBR with the champion. Adoption of the analytics module stalled, two power users left, and they are evaluating a competitor before renewal. The economic buyer is concerned about pricing.";

export const SOURCE_EXAMPLES: Record<string, string> = {
  meeting_notes:
    "QBR with Zephyr Dynamics. Adoption of the analytics module stalled after the Q1 reorg, and two power users left. The champion is happy with support but the economic buyer is concerned about pricing ahead of the May renewal. They mentioned evaluating a competitor.",
  call_transcript:
    "CSM: How has the rollout gone since launch?\nCustomer: Honestly, usage has dropped. Two of our admins left and onboarding the new team stalled. We are frustrated and are looking at alternatives before the renewal in March.",
  email:
    "Subject: Renewal and open issues\n\nHi team, ahead of our renewal we wanted to flag that adoption has been lower than expected and we have an open support ticket about slow dashboards. Leadership is asking about ROI. Can we discuss pricing options?",
  support_ticket:
    "Ticket #4821 (high priority): Dashboards time out for users on the Growth plan. Customer reports this has happened three times this week and is frustrated. Renewal is in 30 days and they are escalating.",
  crm_record:
    "Account: Zephyr Dynamics. Stage: At risk. ARR: 84000. Health: 41. Renewal: 2026-05-15. Last touch: champion flagged stalled adoption and a competitor evaluation. Owner: Priya.",
  chat_message:
    "[Slack #cs-zephyr] Champion just pinged: their VP is questioning the spend and usage is down this quarter. They want a business review before they commit to renewal. Flagging churn risk.",
  document:
    "Internal brief: Zephyr Dynamics expansion blocked by low adoption. Two power users left; onboarding for the replacement admins has not started. Competitor evaluation underway. Renewal at risk in May.",
  web: "",
};

export function exampleForSource(key: string): string {
  const ex = SOURCE_EXAMPLES[key];
  return ex !== undefined && ex !== "" ? ex : EXAMPLE_FALLBACK;
}

export interface RecentIngest {
  id: string;
  title: string;
  source_type: string;
  account_id: string | null;
  chars: number;
  chunks_written: number;
  persisted: string;
  extracted_signals: ExtractedSignal[];
  ts?: number;
}

/** The org's recently ingested interactions, most recent first. */
export async function getRecentIngests(
  signal?: AbortSignal,
): Promise<RecentIngest[]> {
  try {
    const res = await fetch(`${API_BASE}/ingest/recent`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
    if (!res.ok) throw new Error(`GET /ingest/recent failed (${res.status})`);
    const data = (await res.json()) as { items?: RecentIngest[] };
    return Array.isArray(data.items) ? data.items : [];
  } catch {
    return [];
  }
}

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
        id: "",
        account_id: payload.account_id ?? null,
        source_type: "web",
        title: payload.title ?? "",
        domain: payload.domain ?? "customer_success",
        embed_method: "none",
        persisted: "none",
        extracted_signals: [],
        chars: 0,
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
      id: "",
      account_id: payload.account_id ?? null,
      source_type: "web",
      title: payload.title ?? "",
      domain: payload.domain ?? "customer_success",
      embed_method: "none",
      persisted: "none",
      extracted_signals: [],
      chars: 0,
      detail: "Web search unavailable (offline).",
    };
  }
}
