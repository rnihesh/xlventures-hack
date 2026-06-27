// Typed client for the one-click action execution API.
//
// executeAction turns a recommendation into a concrete artifact (email, CRM
// task, or Slack handoff) via POST /execute. listArtifacts reads back the
// artifacts generated for a run via GET /execute/{run_id}.
//
// The backend is offline-safe: when no OPENAI_API_KEY is configured it returns
// deterministic templates. executeAction additionally degrades to a local,
// deterministic artifact when the backend itself is unreachable, so the panel
// always renders something usable in a demo.

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import type { Recommendation } from "@/lib/types";

export type ArtifactType = "email" | "crm_task" | "slack";

export interface EmailArtifact {
  subject: string;
  body: string;
}

export interface CrmTaskArtifact {
  title: string;
  due: string;
  notes: string;
  priority?: string;
}

export interface SlackArtifact {
  channel: string;
  message: string;
}

export type Artifact = EmailArtifact | CrmTaskArtifact | SlackArtifact;

export interface AuditRecord {
  id: string;
  run_id: string | null;
  account_id: string | null;
  artifact_type: ArtifactType;
  action_key: string | null;
  recommendation_id: string | null;
  source: "llm" | "template";
  created_at: string;
  artifact: Artifact;
}

export interface ExecuteResponse {
  artifact: Artifact;
  audit: AuditRecord;
}

export interface ExecutePayload {
  artifact_type: ArtifactType;
  // Pass either a run_id (to use the stored recommendation) or an inline
  // recommendation object. account_id supplies account context.
  run_id?: string | null;
  recommendation?: Recommendation | Record<string, unknown> | null;
  account_id?: string | null;
}

// Result of really dispatching an artifact through its channel (SES email,
// Slack webhook, Gmail, or a CRM task record). The backend never raises when a
// channel is not configured: it returns sent=false with a machine reason so the
// UI can guide the user to connect it in Settings.
export interface SendResult {
  sent: boolean;
  // Logical channel the dispatch used: "ses" | "slack" | "google" | "crm".
  channel?: string;
  // Machine code when not sent, eg "ses_not_configured", "slack_not_configured",
  // "google_not_connected". Used to detect the connect-in-settings state.
  reason?: string;
  // Where it went (recipient email or Slack channel) when sent. For a
  // multi-recipient email this is the comma-joined list of addresses.
  to?: string;
  // Human-friendly detail, surfaced verbatim when present.
  detail?: string;
  // Provider message id when the channel returns one.
  id?: string;
  // Per-recipient breakdown for a multi-recipient email send.
  results?: SendRecipientResult[];
}

// Outcome for a single address in a fan-out email send.
export interface SendRecipientResult {
  to: string;
  sent: boolean;
  reason?: string;
  detail?: string;
}

export interface SendPayload {
  artifact_type: ArtifactType;
  // The possibly edited artifact the user reviewed in the preview.
  artifact: Artifact;
  run_id?: string | null;
  account_id?: string | null;
  recommendation_id?: string | null;
  action_key?: string | null;
  // Email recipient resolution. An email can fan out to several people: any
  // number of saved contacts (`contact_ids`) plus any number of raw addresses
  // (`recipients`). The singular `contact_id` / `to` are kept for back-compat.
  // When none are set the send falls back to the account's contact.
  contact_id?: string | null;
  to?: string | null;
  contact_ids?: string[];
  recipients?: string[];
}

const NOT_CONFIGURED_REASON: Record<ArtifactType, string> = {
  email: "ses_not_configured",
  slack: "slack_not_configured",
  crm_task: "crm_not_configured",
};

/**
 * Really dispatch a (possibly edited) artifact through its channel via
 * POST /execute/send. When the backend is unreachable we degrade to a graceful
 * not-configured result so the panel guides the user to Settings instead of
 * dead-ending or throwing.
 */
export async function sendArtifact(
  payload: SendPayload,
): Promise<SendResult> {
  try {
    const res = await fetch(`${API_BASE}/execute/send`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`POST /execute/send failed (${res.status})`);
    }
    return (await res.json()) as SendResult;
  } catch {
    return {
      sent: false,
      channel: payload.artifact_type,
      reason: NOT_CONFIGURED_REASON[payload.artifact_type],
    };
  }
}

export interface ApprovalHandoffPayload {
  // Pass either a run_id (to use the stored recommendation and its signal) or an
  // inline recommendation object. account_id supplies account context.
  run_id?: string | null;
  recommendation?: Recommendation | Record<string, unknown> | null;
  account_id?: string | null;
}

/**
 * Push a pending recommendation to the org's Slack channel for human sign-off
 * via POST /execute/approval-handoff. The backend posts a rich approval summary
 * to the org's saved webhook and degrades gracefully (sent=false,
 * slack_not_configured) when no webhook is set. When the backend is unreachable
 * we mirror that graceful not-configured result so the UI never dead-ends.
 */
export async function sendApprovalHandoff(
  payload: ApprovalHandoffPayload,
): Promise<SendResult> {
  try {
    const res = await fetch(`${API_BASE}/execute/approval-handoff`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`POST /execute/approval-handoff failed (${res.status})`);
    }
    return (await res.json()) as SendResult;
  } catch {
    return { sent: false, channel: "slack", reason: "slack_not_configured" };
  }
}

/**
 * Generate an artifact from a recommendation. Surfaces the live backend result
 * when reachable; otherwise returns a local, deterministic approximation that
 * mirrors the backend templates so the panel never blanks out.
 */
export async function executeAction(
  payload: ExecutePayload,
): Promise<ExecuteResponse> {
  try {
    const res = await fetch(`${API_BASE}/execute`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`POST /execute failed (${res.status})`);
    }
    return (await res.json()) as ExecuteResponse;
  } catch {
    return localExecute(payload);
  }
}

/** List the artifacts generated for a run, most recent first. */
export async function listArtifacts(runId: string): Promise<AuditRecord[]> {
  try {
    const res = await fetch(
      `${API_BASE}/execute/${encodeURIComponent(runId)}`,
      {
        headers: authHeaders({ Accept: "application/json" }),
        credentials: "include",
        cache: "no-store",
      },
    );
    if (!res.ok) {
      throw new Error(`GET /execute/${runId} failed (${res.status})`);
    }
    return (await res.json()) as AuditRecord[];
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Local, deterministic fallback (mirrors backend templates).
// ---------------------------------------------------------------------------

interface RecLike {
  id?: string;
  action?: { key?: string; title?: string; description?: string };
  rationale?: string;
  risk_opportunity?: { summary?: string };
  expected_impact?: { kpi?: string; estimate?: string };
  confidence?: { label?: string };
  account_id?: string;
  domain?: string;
}

function asRec(payload: ExecutePayload): RecLike {
  const rec = (payload.recommendation ?? {}) as RecLike;
  return rec;
}

function actionTitle(rec: RecLike): string {
  return rec.action?.title ?? "the recommended next step";
}

function impactLine(rec: RecLike): string {
  const kpi = rec.expected_impact?.kpi ?? "";
  const estimate = rec.expected_impact?.estimate ?? "";
  if (kpi && estimate) return `${kpi}: ${estimate}`;
  return kpi || estimate;
}

function accountLabel(payload: ExecutePayload, rec: RecLike): string {
  return payload.account_id ?? rec.account_id ?? "the account";
}

function localArtifact(payload: ExecutePayload): Artifact {
  const rec = asRec(payload);
  const name = accountLabel(payload, rec);
  const title = actionTitle(rec);
  const risk = (rec.risk_opportunity?.summary ?? "").replace(/\.$/, "");
  const impact = impactLine(rec);

  if (payload.artifact_type === "email") {
    const lowerTitle = title.charAt(0).toLowerCase() + title.slice(1);
    const context = risk
      ? `${risk.charAt(0).toLowerCase()}${risk.slice(1)}`
      : "things are tracking on our side";
    const impactSentence = impact ? ` The goal is concrete: ${impact}.` : "";
    return {
      subject: `Quick proposal for ${name}: ${title}`,
      body:
        `Hi ${name} team,\n\n` +
        `I have been reviewing how ${context}. I would like to propose that we ` +
        `${lowerTitle} so we can realign on your goals and lock in the outcomes ` +
        `you signed up for.${impactSentence}\n\n` +
        "Are you open to a short session this week? I will come prepared with a " +
        "tailored plan and clear next steps.\n\nBest,\nYour Customer Success team",
    };
  }

  if (payload.artifact_type === "crm_task") {
    const due = new Date(Date.now() + 1000 * 60 * 60 * 24 * 3)
      .toISOString()
      .slice(0, 10);
    const notes = [
      `Recommended play: ${title}.`,
      rec.rationale ? `Why now: ${rec.rationale}` : "",
      impact ? `Expected impact: ${impact}.` : "",
    ]
      .filter(Boolean)
      .join(" ");
    const high = (rec.confidence?.label ?? "").toLowerCase() === "high";
    return {
      title: `${title} (${name})`,
      due,
      notes,
      priority: high ? "high" : "medium",
    };
  }

  // slack
  const channel =
    rec.domain === "saas_sales" ? "#sales-deals" : "#cs-saves";
  const lines = [
    `:handshake: *Handoff: ${name}*`,
    risk ? `> ${risk}` : "",
    `*Recommended play:* ${title}`,
    impact ? `*Expected impact:* ${impact}` : "",
    "React with :white_check_mark: to take it, or reply to discuss.",
  ].filter(Boolean);
  return { channel, message: lines.join("\n") };
}

function localExecute(payload: ExecutePayload): ExecuteResponse {
  const rec = asRec(payload);
  const artifact = localArtifact(payload);
  const audit: AuditRecord = {
    id: `local_${Date.now()}`,
    run_id: payload.run_id ?? null,
    account_id: accountLabel(payload, rec),
    artifact_type: payload.artifact_type,
    action_key: rec.action?.key ?? null,
    recommendation_id: rec.id ?? null,
    source: "template",
    created_at: new Date().toISOString(),
    artifact,
  };
  return { artifact, audit };
}
