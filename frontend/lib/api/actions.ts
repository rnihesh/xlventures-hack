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
      headers: { "Content-Type": "application/json" },
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
      { headers: { Accept: "application/json" }, cache: "no-store" },
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
