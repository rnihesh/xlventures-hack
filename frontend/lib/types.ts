// Types mirror the FROZEN CONTRACT exactly.

export type EventType =
  | "run.started"
  | "node.started"
  | "node.finished"
  | "token"
  | "recommendation"
  | "hitl.required"
  | "run.finished"
  | "error";

// SSE event envelope (contracts/events.schema.json)
export interface AgentEvent {
  id: string; // uuid
  run_id: string;
  seq: number;
  type: EventType;
  ts: string; // ISO8601
  data: Record<string, unknown>;
}

// Explainable Recommendation Object (contracts/recommendation.schema.json)
export interface RecommendationAction {
  key: string;
  title: string;
  description: string;
}

export interface Evidence {
  claim: string;
  source_id: string;
  source_type: string;
  snippet: string;
  span: {
    start: number;
    end: number;
  };
  score?: number;
}

// A ranked candidate action the engine weighed before choosing. The chosen play
// is included with why_not === null; runner-ups carry a "why not" explanation.
export interface Alternative {
  action: RecommendationAction;
  score: number; // 0..1 expected value
  rationale: string;
  why_not: string | null;
  chosen?: boolean;
}

export interface Signals {
  supporting: string[];
  contradicting: string[];
}

export interface Confidence {
  score: number; // 0..1
  method: string;
  label: string;
}

export type RiskOpportunityType = "risk" | "opportunity";

export interface RiskOpportunity {
  type: RiskOpportunityType;
  summary: string;
}

export type ImpactDirection = "up" | "down";

export interface ExpectedImpact {
  kpi: string;
  direction: ImpactDirection;
  estimate: string;
}

export type RecommendationStatus =
  | "proposed"
  | "approved"
  | "rejected"
  | "edited";

export interface Recommendation {
  id: string;
  run_id: string;
  account_id: string;
  domain: string;
  action: RecommendationAction;
  rationale: string;
  evidence: Evidence[];
  signals: Signals;
  confidence: Confidence;
  risk_opportunity: RiskOpportunity;
  counterfactual: string;
  expected_impact: ExpectedImpact;
  // Optional extra field: top-3 ranked alternatives with why-not reasons.
  alternatives?: Alternative[];
  status: RecommendationStatus;
  created_at: string; // ISO8601
}

// REST request/response shapes from the contract.
export interface Signal {
  type: string;
  content: string;
}

export interface CreateRunRequest {
  domain: string;
  account_id: string;
  signal: Signal;
}

export interface CreateRunResponse {
  run_id: string;
}

export type HitlDecision = "approve" | "reject" | "edit";

export interface HitlRequest {
  decision: HitlDecision;
  edited_action: RecommendationAction | Record<string, unknown> | null;
  reason: string | null;
}

export interface HitlResponse {
  status: string;
}

export interface HealthResponse {
  status: string;
}

// ---------------------------------------------------------------------------
// REST additions (frozen interface). Accounts, domains, learning, eval.
// ---------------------------------------------------------------------------

export type RiskLevel = "high" | "medium" | "low" | string;

// GET /accounts
export interface Account {
  account_id: string;
  name: string;
  domain: string;
  health_score: number; // 0..100
  risk_level: RiskLevel;
  last_signal: string;
  arr: number;
}

// A point on the account signal timeline. Shape is intentionally permissive
// so the UI renders whatever the backend supplies without breaking.
export interface AccountSignal {
  type?: string;
  content?: string;
  label?: string;
  summary?: string;
  ts?: string;
  timestamp?: string;
  source?: string;
  severity?: string;
  [key: string]: unknown;
}

// GET /accounts/{id}
export interface AccountProfile extends Partial<Account> {
  account_id: string;
  name?: string;
  domain?: string;
  health_score?: number;
  risk_level?: RiskLevel;
  arr?: number;
  segment?: string;
  owner?: string;
  renewal_date?: string;
  plan?: string;
  seats?: number;
  [key: string]: unknown;
}

export interface AccountDetail {
  profile: AccountProfile;
  signals: AccountSignal[];
  history: Recommendation[];
  current: Recommendation | null;
}

// GET /domains
export interface DomainSummary {
  key: string;
  display_name: string;
  actions_count: number;
  decision_points_count: number;
}

// GET /learning
export interface LearningEpisode {
  id?: string;
  episode_id?: string;
  account_id?: string;
  account_name?: string;
  domain?: string;
  situation?: string;
  action_key?: string;
  action_title?: string;
  decision?: string;
  reason?: string | null;
  outcome?: string | Record<string, unknown> | null;
  created_at?: string;
  [key: string]: unknown;
}

export interface BeforeAfter {
  kpi: string;
  before: number;
  after: number;
  note: string;
}

export interface Learning {
  episodes: LearningEpisode[];
  accepted_rate: number; // 0..1
  before_after: BeforeAfter;
}

// GET /eval
export interface EvalSuite {
  name: string;
  metric: string;
  score: number;
  passed: number;
  total: number;
}

export interface EvalOutcomes {
  kpi: string;
  baseline: number;
  projected: number;
  unit: string;
}

export interface EvalReport {
  suites: EvalSuite[];
  outcomes: EvalOutcomes;
}
