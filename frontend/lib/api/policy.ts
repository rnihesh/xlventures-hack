// Typed client for the declarative guardrail / policy layer.
//
// getPolicies reads a domain's declared rules via GET /policy/{domain}.
// evaluatePolicy checks a recommendation against those rules via
// POST /policy/evaluate and returns one pass/fail/warn gate per rule.
//
// Both degrade to a local, deterministic evaluator that mirrors the backend
// engine, so the policy panel renders correctly even with no backend, no
// OPENAI_API_KEY, and no database.

import { API_BASE, SEED_ACCOUNTS } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import type { PolicyGate } from "@/lib/types";

export type PolicySeverity = "low" | "medium" | "high" | string;

// A declarative rule as authored in a domain pack.
export interface PolicyRule {
  id: string;
  description: string;
  type: string;
  condition: Record<string, unknown>;
  severity: PolicySeverity;
  requires_approval: boolean;
}

export interface PolicyEvaluateRequest {
  recommendation: Record<string, unknown>;
  account_id?: string | null;
  domain: string;
}

export interface PolicySummary {
  total: number;
  passed: number;
  warned: number;
  failed: number;
  requires_approval: boolean;
}

export interface PolicyEvaluateResponse {
  domain: string;
  account_id: string | null;
  results: PolicyGate[];
  summary: PolicySummary;
  requires_approval: boolean;
}

/** Fetch a domain's declared policy rules, falling back to local defaults. */
export async function getPolicies(domain: string): Promise<PolicyRule[]> {
  try {
    const res = await fetch(
      `${API_BASE}/policy/${encodeURIComponent(domain)}`,
      {
        headers: authHeaders({ Accept: "application/json" }),
        credentials: "include",
        cache: "no-store",
      },
    );
    if (!res.ok) throw new Error(`GET /policy/${domain} failed (${res.status})`);
    const data = (await res.json()) as { policies?: PolicyRule[] };
    return data.policies ?? localPolicies(domain);
  } catch {
    return localPolicies(domain);
  }
}

/**
 * Evaluate a recommendation against a domain's policy rules. Surfaces the live
 * backend result when reachable; otherwise mirrors the backend engine locally
 * so the panel always shows meaningful gates.
 */
export async function evaluatePolicy(
  payload: PolicyEvaluateRequest,
): Promise<PolicyEvaluateResponse> {
  try {
    const res = await fetch(`${API_BASE}/policy/evaluate`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`POST /policy/evaluate failed (${res.status})`);
    return (await res.json()) as PolicyEvaluateResponse;
  } catch {
    return localEvaluate(payload);
  }
}

// ---------------------------------------------------------------------------
// Local, deterministic fallback. Mirrors backend/app/policy so the guardrail
// layer behaves identically offline.
// ---------------------------------------------------------------------------

const LOCAL_POLICIES: Record<string, PolicyRule[]> = {
  customer_success: [
    {
      id: "discount_cap_15",
      description: "Retention discounts above 15% require deal-desk approval.",
      type: "discount_cap",
      condition: { max_pct: 15 },
      severity: "high",
      requires_approval: true,
    },
    {
      id: "exec_escalation_signoff",
      description: "Executive escalations require Customer Success manager sign-off.",
      type: "action_requires_approval",
      condition: { actions: ["open_executive_escalation"] },
      severity: "high",
      requires_approval: true,
    },
    {
      id: "outreach_cooldown",
      description: "No new customer outreach within 7 days of the last touch.",
      type: "cooldown_window",
      condition: {
        min_days: 7,
        applies_to_actions: [
          "schedule_executive_business_review",
          "launch_adoption_campaign",
          "open_executive_escalation",
        ],
      },
      severity: "medium",
      requires_approval: false,
    },
    {
      id: "low_confidence_review",
      description: "Recommendations below 60% confidence need human review.",
      type: "confidence_floor",
      condition: { min: 0.6 },
      severity: "medium",
      requires_approval: true,
    },
    {
      id: "high_value_account_review",
      description: "High-ARR accounts (at or above $250k) get an extra review touch.",
      type: "field_threshold",
      condition: { field: "account.arr", op: "gte", value: 250000, on_violation: "warn" },
      severity: "low",
      requires_approval: false,
    },
  ],
  saas_sales: [
    {
      id: "discount_cap_20",
      description: "Proposal discounts above 20% require sales manager approval.",
      type: "discount_cap",
      condition: { max_pct: 20 },
      severity: "high",
      requires_approval: true,
    },
    {
      id: "closing_proposal_signoff",
      description: "Sending a closing proposal requires manager sign-off.",
      type: "action_requires_approval",
      condition: { actions: ["send_proposal"] },
      severity: "high",
      requires_approval: true,
    },
    {
      id: "buyer_outreach_cooldown",
      description: "No buyer outreach within 5 days of the last contact.",
      type: "cooldown_window",
      condition: { min_days: 5, applies_to_actions: ["re_engage_buyer", "send_proposal"] },
      severity: "medium",
      requires_approval: false,
    },
  ],
};

function localPolicies(domain: string): PolicyRule[] {
  return LOCAL_POLICIES[domain] ?? [];
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = parseFloat(v.replace(/[^0-9.\-]/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

const DISCOUNT_HINT = /discount|concession|save|credit|rebate|waiver/i;

function discountPct(rec: Record<string, unknown>): number {
  const action = (rec.action ?? {}) as Record<string, unknown>;
  const explicit = num(rec.discount_pct) ?? num(action.discount_pct);
  if (explicit !== null) return explicit;
  const key = String(action.key ?? "");
  const text = `${action.title ?? ""} ${action.description ?? ""}`;
  if (DISCOUNT_HINT.test(key) || DISCOUNT_HINT.test(text)) {
    const m = text.match(/(\d+(?:\.\d+)?)\s*%/);
    if (m) return parseFloat(m[1]);
  }
  return 0;
}

function localContext(payload: PolicyEvaluateRequest) {
  const rec = payload.recommendation ?? {};
  const action = (rec.action ?? {}) as Record<string, unknown>;
  const confidence = (rec.confidence ?? {}) as Record<string, unknown>;
  const risk = (rec.risk_opportunity ?? {}) as Record<string, unknown>;
  const seed = SEED_ACCOUNTS.find((a) => a.account_id === payload.account_id);
  return {
    action_key: String(action.key ?? ""),
    action_title: String(action.title ?? action.key ?? ""),
    discount_pct: discountPct(rec),
    confidence: num(confidence.score),
    risk_type: String(risk.type ?? ""),
    account: {
      arr: num(seed?.arr),
      days_since_last_outreach: num(
        (rec as Record<string, unknown>).days_since_last_outreach,
      ),
    } as Record<string, number | null>,
  };
}

type Ctx = ReturnType<typeof localContext>;

function evalRule(ctx: Ctx, rule: PolicyRule): { status: PolicyGate["status"]; detail: string } {
  const c = rule.condition;
  switch (rule.type) {
    case "discount_cap": {
      const max = num(c.max_pct);
      const d = ctx.discount_pct;
      if (max === null) return { status: "pass", detail: "No discount cap configured." };
      if (d <= max)
        return {
          status: "pass",
          detail:
            d <= 0
              ? `No discount proposed; the ${max}% cap is not engaged.`
              : `Proposed discount ${d}% is within the ${max}% cap.`,
        };
      return {
        status: "fail",
        detail: `Proposed discount ${d}% exceeds the ${max}% cap and needs sign-off.`,
      };
    }
    case "action_requires_approval": {
      const actions = (c.actions as string[]) ?? [];
      if (actions.includes(ctx.action_key))
        return { status: "warn", detail: `Action '${ctx.action_title}' is gated and needs sign-off.` };
      return { status: "pass", detail: "Chosen action is not on the approval-gated list." };
    }
    case "cooldown_window": {
      const applies = (c.applies_to_actions as string[]) ?? [];
      if (applies.length && !applies.includes(ctx.action_key))
        return { status: "pass", detail: "Not an outreach action; cooldown does not apply." };
      const minDays = num(c.min_days) ?? 0;
      const days = ctx.account.days_since_last_outreach;
      if (days === null)
        return { status: "pass", detail: "No recent outreach on record; cooldown window is clear." };
      if (days < minDays)
        return {
          status: "warn",
          detail: `Last outreach was ${days}d ago, inside the ${minDays}d cooldown window.`,
        };
      return { status: "pass", detail: `Last outreach was ${days}d ago, clear of the ${minDays}d cooldown.` };
    }
    case "confidence_floor": {
      const min = num(c.min);
      const conf = ctx.confidence;
      if (min === null) return { status: "pass", detail: "No confidence floor configured." };
      if (conf === null) return { status: "pass", detail: "No confidence score available to check." };
      if (conf < min)
        return {
          status: "warn",
          detail: `Confidence ${Math.round(conf * 100)}% is below the ${Math.round(min * 100)}% review floor.`,
        };
      return {
        status: "pass",
        detail: `Confidence ${Math.round(conf * 100)}% clears the ${Math.round(min * 100)}% floor.`,
      };
    }
    case "field_threshold": {
      const field = String(c.field ?? "");
      const op = String(c.op ?? "");
      const value = num(c.value);
      const actual = field === "account.arr" ? ctx.account.arr : null;
      if (!field || value === null || actual === null)
        return { status: "pass", detail: `No value for '${field}' to evaluate.` };
      const ops: Record<string, (a: number, b: number) => boolean> = {
        lt: (a, b) => a < b,
        lte: (a, b) => a <= b,
        gt: (a, b) => a > b,
        gte: (a, b) => a >= b,
        eq: (a, b) => a === b,
        ne: (a, b) => a !== b,
      };
      const fn = ops[op];
      if (!fn) return { status: "pass", detail: "Threshold guard not fully configured; skipped." };
      if (fn(actual, value)) {
        const status = c.on_violation === "fail" ? "fail" : "warn";
        return { status, detail: `'${field}' is ${actual} (${op} ${value}); guard tripped.` };
      }
      return { status: "pass", detail: `'${field}' is ${actual}; within guard limits.` };
    }
    default:
      return { status: "pass", detail: `Rule type '${rule.type}' is not enforced.` };
  }
}

function localEvaluate(payload: PolicyEvaluateRequest): PolicyEvaluateResponse {
  const ctx = localContext(payload);
  const rules = localPolicies(payload.domain);
  const results: PolicyGate[] = rules.map((rule) => {
    const { status, detail } = evalRule(ctx, rule);
    return {
      rule_id: rule.id,
      description: rule.description,
      status,
      detail,
      severity: rule.severity,
      requires_approval: rule.requires_approval && status !== "pass",
    } as PolicyGate;
  });
  const summary: PolicySummary = {
    total: results.length,
    passed: results.filter((r) => r.status === "pass").length,
    warned: results.filter((r) => r.status === "warn").length,
    failed: results.filter((r) => r.status === "fail").length,
    requires_approval: results.some((r) => r.requires_approval),
  };
  return {
    domain: payload.domain,
    account_id: payload.account_id ?? null,
    results,
    summary,
    requires_approval: summary.requires_approval,
  };
}
