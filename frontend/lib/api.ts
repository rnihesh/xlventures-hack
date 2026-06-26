// Typed fetch client for the Aperture REST + SSE API.
//
// Every read endpoint falls back to deterministic seed data when the backend
// is unreachable, so the UI boots and demos cleanly offline. Mutations
// (createRun, hitl) surface real errors because they require the live agent.
// The what-if endpoint computes a counterfactual; it degrades to a local,
// deterministic approximation when the backend is unreachable so the demo
// never blanks out.

import type {
  Account,
  AccountDetail,
  CreateRunRequest,
  CreateRunResponse,
  DomainSummary,
  EvalReport,
  HealthResponse,
  HitlDecision,
  HitlRequest,
  HitlResponse,
  Learning,
  Recommendation,
  RecommendationAction,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface GetOptions {
  // When provided, a failed/offline request resolves to this instead of throwing.
  // Used for read endpoints so the demo never blanks out.
  fallback?: unknown;
  signal?: AbortSignal;
}

async function getJson<T>(path: string, opts: GetOptions = {}): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: opts.signal,
    });
    if (!res.ok) {
      throw new ApiError(`GET ${path} failed (${res.status})`, res.status);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (opts.fallback !== undefined) {
      return opts.fallback as T;
    }
    throw err;
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new ApiError(`POST ${path} failed (${res.status})`, res.status);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Public API surface
// ---------------------------------------------------------------------------

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health", {
    fallback: { status: "offline" },
    signal,
  });
}

export function getAccounts(signal?: AbortSignal): Promise<Account[]> {
  return getJson<Account[]>("/accounts", { fallback: SEED_ACCOUNTS, signal });
}

export async function getAccount(
  id: string,
  signal?: AbortSignal,
): Promise<AccountDetail> {
  return getJson<AccountDetail>(`/accounts/${encodeURIComponent(id)}`, {
    fallback: seedAccountDetail(id),
    signal,
  });
}

export function getDomains(signal?: AbortSignal): Promise<DomainSummary[]> {
  return getJson<DomainSummary[]>("/domains", {
    fallback: SEED_DOMAINS,
    signal,
  });
}

export function getLearning(signal?: AbortSignal): Promise<Learning> {
  return getJson<Learning>("/learning", { fallback: SEED_LEARNING, signal });
}

export function getEval(signal?: AbortSignal): Promise<EvalReport> {
  return getJson<EvalReport>("/eval", { fallback: SEED_EVAL, signal });
}

export function createRun(
  body: CreateRunRequest,
): Promise<CreateRunResponse> {
  return postJson<CreateRunResponse>("/runs", body);
}

export function hitl(
  runId: string,
  decision: HitlDecision,
  editedAction: RecommendationAction | null,
  reason: string | null,
): Promise<HitlResponse> {
  const payload: HitlRequest = {
    decision,
    edited_action: editedAction,
    reason,
  };
  return postJson<HitlResponse>(
    `/runs/${encodeURIComponent(runId)}/hitl`,
    payload,
  );
}

export function streamUrl(runId: string): string {
  return `${API_BASE}/runs/${encodeURIComponent(runId)}/stream`;
}

// ---------------------------------------------------------------------------
// Counterfactual "what-if" (POST /whatif)
// ---------------------------------------------------------------------------

// The signals a user may nudge. All optional; omitted ones keep the baseline.
export interface WhatIfOverrides {
  usage_trend?: number; // QoQ usage change, percent
  nps?: number; // 0..10
  arr?: number; // annual recurring revenue / contract size
  [key: string]: number | undefined;
}

export interface WhatIfRequest {
  domain: string;
  account_id: string;
  overrides: WhatIfOverrides;
}

export interface WhatIfBaseline {
  action: RecommendationAction;
  confidence: number; // 0..1
  risk_score: number; // 0..1
}

export interface WhatIfPressures {
  usage_pressure: number;
  nps_pressure: number;
  mean_pressure: number;
  conflict: number;
}

export interface WhatIfResponse {
  recommendation: Recommendation;
  baseline: WhatIfBaseline;
  confidence_delta: number; // whatif - baseline, in 0..1 points
  risk_score: { baseline: number; whatif: number };
  pressures: WhatIfPressures;
  applied_overrides: { usage_trend: number; nps: number; arr: number };
  action_changed: boolean;
}

/**
 * Re-run the decision pipeline with a couple of overridden input signals and
 * report how the recommendation and confidence shift versus the baseline.
 *
 * Surfaces the live backend result when reachable; otherwise returns a local,
 * deterministic approximation (mirrors the backend counterfactual math) so the
 * panel still demonstrates the effect offline.
 */
export async function whatIf(payload: WhatIfRequest): Promise<WhatIfResponse> {
  try {
    return await postJson<WhatIfResponse>("/whatif", payload);
  } catch {
    return localWhatIf(payload);
  }
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function round3(v: number): number {
  return Math.round(v * 1000) / 1000;
}

function signPct(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(0)}%`;
}

function formatUsd(v: number): string {
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

function seedArr(accountId: string): number {
  return SEED_ACCOUNTS.find((a) => a.account_id === accountId)?.arr ?? 120000;
}

// Offline approximation of the backend's counterfactual layer. Deterministic
// so the demo is stable when the agent is unreachable.
function localWhatIf(payload: WhatIfRequest): WhatIfResponse {
  const seed = seedRecommendation(payload.account_id);
  const baseRisk = 0.62;
  const baseConf = seed.confidence.score;

  const usageTrend = payload.overrides.usage_trend ?? -10;
  const nps = payload.overrides.nps ?? 7;
  const arr = payload.overrides.arr ?? seedArr(payload.account_id);

  const usagePressure = clamp(-usageTrend / 40, -1, 1);
  const npsPressure = clamp((7 - nps) / 7, -1, 1);
  const meanPressure = clamp(0.6 * usagePressure + 0.4 * npsPressure, -1, 1);
  const conflict = Math.abs(usagePressure - npsPressure) / 2;

  const newRisk = clamp(round3(baseRisk + 0.3 * meanPressure), 0.05, 0.95);
  const direction = seed.risk_opportunity.type === "risk" ? 1 : -1;
  const alignment = direction * meanPressure;
  const newConf = clamp(round3(baseConf + 0.22 * alignment - 0.16 * conflict), 0.05, 0.97);

  // Flip to a more decisive play when risk runs high, a lighter one when low.
  const escalated: RecommendationAction = {
    key: "open_executive_escalation",
    title: "Open an executive escalation with the buying committee",
    description:
      "Pull in your VP of CS and the customer's economic buyer to arrest the decline before renewal.",
  };
  const lightTouch: RecommendationAction = {
    key: "launch_adoption_campaign",
    title: "Launch a targeted adoption campaign",
    description:
      "Drive feature adoption with a guided enablement path rather than a senior intervention.",
  };
  let action = seed.action;
  if (newRisk >= 0.7) action = escalated;
  else if (newRisk <= 0.45) action = lightTouch;
  const actionChanged = action.key !== seed.action.key;

  const riskPhrase =
    newRisk > baseRisk + 0.02
      ? "elevated"
      : newRisk < baseRisk - 0.02
        ? "reduced"
        : "roughly unchanged";

  const recommendation: Recommendation = {
    ...seed,
    id: `whatif_${payload.account_id}_${Date.now()}`,
    account_id: payload.account_id,
    domain: payload.domain,
    action,
    status: "proposed",
    confidence: {
      score: newConf,
      method: "counterfactual_whatif",
      label: newConf >= 0.75 ? "high" : newConf >= 0.5 ? "medium" : "low",
    },
    counterfactual:
      `With usage trend ${signPct(usageTrend)} QoQ, NPS ${nps.toFixed(0)}/10, and ARR ` +
      `${formatUsd(arr)}, churn risk is ${riskPhrase} (${baseRisk.toFixed(2)} -> ${newRisk.toFixed(2)}). ` +
      (actionChanged
        ? `The engine now favors '${action.title}'.`
        : "The recommended play holds, with recalibrated confidence."),
  };

  return {
    recommendation,
    baseline: {
      action: seed.action,
      confidence: round3(baseConf),
      risk_score: round3(baseRisk),
    },
    confidence_delta: round3(newConf - baseConf),
    risk_score: { baseline: round3(baseRisk), whatif: newRisk },
    pressures: {
      usage_pressure: round3(usagePressure),
      nps_pressure: round3(npsPressure),
      mean_pressure: round3(meanPressure),
      conflict: round3(conflict),
    },
    applied_overrides: { usage_trend: usageTrend, nps, arr },
    action_changed: actionChanged,
  };
}

// ---------------------------------------------------------------------------
// Seed data (offline fallback). Mirrors the customer_success domain pack.
// ---------------------------------------------------------------------------

export const SEED_ACCOUNTS: Account[] = [
  {
    account_id: "acct_001",
    name: "Northwind Labs",
    domain: "customer_success",
    health_score: 38,
    risk_level: "high",
    last_signal: "Support tickets up 40% MoM and last QBR skipped",
    arr: 240000,
  },
  {
    account_id: "acct_002",
    name: "Helios Manufacturing",
    domain: "customer_success",
    health_score: 54,
    risk_level: "medium",
    last_signal: "Weekly active users down 18% over 30 days",
    arr: 180000,
  },
  {
    account_id: "acct_003",
    name: "Vertex Analytics",
    domain: "customer_success",
    health_score: 81,
    risk_level: "low",
    last_signal: "Champion requested SSO and 25 additional seats",
    arr: 320000,
  },
  {
    account_id: "acct_004",
    name: "Cobalt Retail Group",
    domain: "saas_sales",
    health_score: 46,
    risk_level: "high",
    last_signal: "Renewal in 45 days, no executive sponsor identified",
    arr: 96000,
  },
  {
    account_id: "acct_005",
    name: "Meridian Health",
    domain: "customer_success",
    health_score: 67,
    risk_level: "medium",
    last_signal: "Onboarding stalled at integration milestone",
    arr: 150000,
  },
  {
    account_id: "acct_006",
    name: "Atlas Logistics",
    domain: "saas_sales",
    health_score: 88,
    risk_level: "low",
    last_signal: "Pilot exceeded usage targets, ready for expansion",
    arr: 72000,
  },
];

const SEED_DOMAINS: DomainSummary[] = [
  {
    key: "customer_success",
    display_name: "Customer Success and Churn Prevention",
    actions_count: 9,
    decision_points_count: 4,
  },
  {
    key: "saas_sales",
    display_name: "SaaS Sales and Expansion",
    actions_count: 7,
    decision_points_count: 3,
  },
];

function seedRecommendation(
  accountId: string,
  overrides: Partial<Recommendation> = {},
): Recommendation {
  const base: Recommendation = {
    id: `rec_${accountId}_seed`,
    run_id: `run_${accountId}_seed`,
    account_id: accountId,
    domain: "customer_success",
    action: {
      key: "schedule_executive_business_review",
      title: "Schedule an executive business review within 7 days",
      description:
        "Bring the account sponsor and your VP of CS together to realign on value, surface blockers driving the ticket spike, and reaffirm the renewal path.",
    },
    rationale:
      "A 40% month-over-month rise in support tickets combined with a skipped QBR is a classic pre-churn pattern for high-ARR accounts. An executive business review re-establishes the relationship and creates a forum to resolve the underlying issues before renewal.",
    evidence: [
      {
        claim: "Support ticket volume rose 40% month over month.",
        source_id: "ticket_metrics_2026_06",
        source_type: "usage_metric",
        snippet: "Open tickets increased from 12 to 17 (+40%) versus the prior month.",
        span: { start: 0, end: 58 },
        score: 0.92,
      },
      {
        claim: "The most recent quarterly business review was skipped.",
        source_id: "crm_activity_log",
        source_type: "crm_record",
        snippet: "QBR scheduled for May was cancelled by customer and not rescheduled.",
        span: { start: 0, end: 66 },
        score: 0.81,
      },
    ],
    signals: {
      supporting: [
        "Ticket volume +40% MoM",
        "QBR skipped",
        "High ARR at renewal",
      ],
      contradicting: ["NPS still 8/10", "Champion remains engaged"],
    },
    confidence: {
      score: 0.84,
      method: "evidence_weighted_ensemble",
      label: "high",
    },
    risk_opportunity: {
      type: "risk",
      summary:
        "240k ARR account showing early churn signals 90 days from renewal.",
    },
    counterfactual:
      "If no executive touch happens before renewal, projected churn probability rises from 31% to roughly 58%.",
    expected_impact: {
      kpi: "Net revenue retention",
      direction: "up",
      estimate: "+2.1 pts on the at-risk cohort",
    },
    status: "proposed",
    created_at: new Date(Date.now() - 1000 * 60 * 60 * 6).toISOString(),
  };
  return { ...base, ...overrides };
}

function seedAccountDetail(id: string): AccountDetail {
  const profile =
    SEED_ACCOUNTS.find((a) => a.account_id === id) ?? SEED_ACCOUNTS[0];
  return {
    profile: {
      ...profile,
      segment: "Enterprise",
      owner: "J. Okafor (CSM)",
      plan: "Scale Annual",
      seats: 240,
      renewal_date: "2026-09-30",
    },
    signals: [
      {
        type: "usage_metric",
        label: "Support tickets +40% MoM",
        content:
          "Open tickets rose from 12 to 17 versus prior month, concentrated in the data import workflow.",
        ts: new Date(Date.now() - 1000 * 60 * 60 * 24 * 2).toISOString(),
        severity: "high",
        source: "Zendesk",
      },
      {
        type: "crm_record",
        label: "QBR cancelled",
        content: "May quarterly business review cancelled by customer, not rescheduled.",
        ts: new Date(Date.now() - 1000 * 60 * 60 * 24 * 9).toISOString(),
        severity: "medium",
        source: "Salesforce",
      },
      {
        type: "engagement",
        label: "Champion logged in 3x this week",
        content: "Primary champion remains active in the analytics module.",
        ts: new Date(Date.now() - 1000 * 60 * 60 * 24 * 12).toISOString(),
        severity: "low",
        source: "Product telemetry",
      },
    ],
    history: [
      seedRecommendation(id, {
        id: `rec_${id}_h1`,
        status: "approved",
        action: {
          key: "share_adoption_playbook",
          title: "Share the data-import adoption playbook with the champion",
          description:
            "Send the curated enablement path to reduce the support burden on the import workflow.",
        },
        created_at: new Date(
          Date.now() - 1000 * 60 * 60 * 24 * 14,
        ).toISOString(),
      }),
    ],
    current: seedRecommendation(id),
  };
}

const SEED_LEARNING: Learning = {
  accepted_rate: 0.72,
  before_after: {
    kpi: "Gross renewal rate",
    before: 84,
    after: 91,
    note: "Across accounts where a recommended save play was accepted.",
  },
  episodes: [
    {
      id: "ep_001",
      account_id: "acct_001",
      account_name: "Northwind Labs",
      domain: "customer_success",
      situation: "Ticket spike plus skipped QBR before renewal",
      action_key: "schedule_executive_business_review",
      action_title: "Schedule an executive business review",
      decision: "approve",
      outcome: "QBR booked, renewal secured",
      created_at: new Date(Date.now() - 1000 * 60 * 60 * 24 * 3).toISOString(),
    },
    {
      id: "ep_002",
      account_id: "acct_002",
      account_name: "Helios Manufacturing",
      domain: "customer_success",
      situation: "Usage decline with no executive sponsor",
      action_key: "offer_value_realization_workshop",
      action_title: "Offer a value realization workshop",
      decision: "edit",
      reason: "CSM preferred a lighter-touch check-in first",
      outcome: "Workshop scheduled for next sprint",
      created_at: new Date(Date.now() - 1000 * 60 * 60 * 24 * 6).toISOString(),
    },
    {
      id: "ep_003",
      account_id: "acct_004",
      account_name: "Cobalt Retail Group",
      domain: "saas_sales",
      situation: "Renewal approaching without identified sponsor",
      action_key: "map_executive_sponsor",
      action_title: "Map and engage an executive sponsor",
      decision: "reject",
      reason: "Account already in procurement, too late for new contacts",
      outcome: "Closed lost",
      created_at: new Date(Date.now() - 1000 * 60 * 60 * 24 * 11).toISOString(),
    },
  ],
};

const SEED_EVAL: EvalReport = {
  outcomes: {
    kpi: "ARR protected per quarter",
    baseline: 1.2,
    projected: 1.9,
    unit: "$M",
  },
  suites: [
    { name: "Grounding faithfulness", metric: "citation accuracy", score: 0.94, passed: 47, total: 50 },
    { name: "Action validity", metric: "schema + policy pass", score: 0.98, passed: 49, total: 50 },
    { name: "Confidence calibration", metric: "ECE (inverted)", score: 0.89, passed: 18, total: 20 },
    { name: "Guardrail compliance", metric: "policy gates honored", score: 1.0, passed: 24, total: 24 },
  ],
};
