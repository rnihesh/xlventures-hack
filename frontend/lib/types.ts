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
