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

// A concrete fact the engine does NOT yet have, that would change or strengthen
// the recommendation (workflow step three: name the missing information).
export interface MissingInformation {
  gap: string;
  why_it_matters: string;
  suggested_source: string;
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
  // Optional extra field: concrete missing facts (what we still need to know).
  missing_information?: MissingInformation[];
  // Optional policy gates evaluated against the chosen action (see PolicyGate).
  policy?: PolicyGate[];
  status: RecommendationStatus;
  created_at: string; // ISO8601
}

// REST request/response shapes from the contract.
export interface Signal {
  type: string;
  content: string;
}

// GET /runs/{id}/brief
// A self-contained, exportable decision brief projected from a stored run: the
// one-pager a CSM hands to leadership. Every field is read from the persisted
// run/episode (no re-run, no LLM), so the shape mirrors the recommendation plus
// the human decision and recorded outcome.
export interface BriefAccount {
  account_id: string;
  name: string;
  domain: string;
  health_score: number | null;
  stage: string | null;
}

export interface BriefHumanDecision {
  decision: string | null;
  edited_action: Record<string, unknown> | null;
  reason: string | null;
  recorded_at: string | null;
}

export interface BriefOutcome {
  decision: string;
  reason: string | null;
  metrics: Record<string, unknown>;
  recorded_at: string | null;
}

export interface DecisionBriefData {
  run_id: string;
  generated_at: string;
  status?: string;
  account: BriefAccount;
  signal: Signal;
  recommendation: {
    id: string | null;
    status: RecommendationStatus | string | null;
    action: RecommendationAction;
    reasoning: string;
    risk_opportunity: RiskOpportunity | null;
    counterfactual: string | null;
  };
  confidence: Confidence;
  expected_impact: ExpectedImpact | null;
  evidence: Evidence[];
  signals: Signals;
  alternatives: Alternative[];
  policy: {
    results: PolicyGate[];
    summary: {
      total: number;
      passed: number;
      warned: number;
      failed: number;
      requires_approval: boolean;
    };
  } | null;
  missing_information: MissingInformation[];
  human_decision: BriefHumanDecision | null;
  outcome: BriefOutcome | null;
}

export interface CreateRunRequest {
  domain: string;
  account_id: string;
  signal: Signal;
}

export interface CreateRunResponse {
  run_id: string;
}

// Account 360 audit timeline (GET /accounts/{id}/timeline). One merged,
// newest-first stream of everything the platform knows about an account.
export type TimelineKind =
  | "interaction"
  | "recommendation"
  | "decision"
  | "outcome";

export interface TimelineEvent {
  id: string;
  kind: TimelineKind;
  ts: string | null;
  title: string;
  summary?: string | null;
  // interaction
  source_type?: string;
  text?: string | null;
  // recommendation
  action?: RecommendationAction;
  confidence?: Confidence | { score?: number | null; label?: string | null; method?: string | null };
  // decision
  decision?: string;
  reason?: string | null;
  // outcome
  metrics?: Record<string, unknown>;
  episode_id?: string;
}

export interface AccountTimeline {
  account_id: string;
  name: string;
  events: TimelineEvent[];
  counts: {
    interaction: number;
    recommendation: number;
    decision: number;
    outcome: number;
    total: number;
  };
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

// A source document backing an account: the org's own ingested interactions
// (uploaded crm-notes / transcript / email) and, for the Demo org, seed docs.
export interface AccountDocument {
  id: string;
  source_type?: string;
  title?: string;
  excerpt?: string;
  ts?: string | null;
}

export interface AccountDetail {
  profile: AccountProfile;
  signals: AccountSignal[];
  history: Recommendation[];
  documents?: AccountDocument[];
  current: Recommendation | null;
}

// GET /domains
export interface DomainSummary {
  key: string;
  display_name: string;
  actions_count: number;
  decision_points_count: number;
  // Present when the list distinguishes base packs from org-uploaded packs.
  source?: "base" | "org";
  editable?: boolean;
  created_at?: string;
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
  // True only once real outcomes carry a measured NRR. When false the loop is
  // empty and before/after are zeros (honest empty state, not fabricated).
  has_data?: boolean;
}

export interface Learning {
  episodes: LearningEpisode[];
  accepted_rate: number; // 0..1
  before_after: BeforeAfter;
  // Counts of decided/accepted episodes from real outcomes (optional).
  decided?: number;
  accepted?: number;
}

// GET /eval
export interface EvalSuite {
  name: string;
  metric: string;
  score: number;
  passed: number;
  total: number;
  // Backend's verdict (score over the suite threshold). Preferred over a strict
  // passed===total check so a strong-but-imperfect suite is not shown as failing.
  healthy?: boolean;
  // Org-scoped suite (Outcome Lift) with no data yet: awaiting, not failing.
  no_data?: boolean;
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

// ---------------------------------------------------------------------------
// Action artifacts and policy gates.
//
// An Artifact is a concrete, editable output the agent drafts for a chosen
// action: a customer email, a CRM follow-up task, or a Slack message. The
// discriminated union below lets the UI render the right editor per kind while
// keeping a stable `kind` field for switching.
// ---------------------------------------------------------------------------

export type ArtifactKind = "email" | "crm_task" | "slack";

// Draft email to a stakeholder. `to` may carry one or multiple recipients.
export interface EmailArtifact {
  kind: "email";
  to?: string;
  cc?: string;
  subject: string;
  body: string;
}

export type CrmTaskPriority = "high" | "medium" | "low" | string;

// Follow-up task to push into the CRM (e.g. Salesforce, HubSpot).
export interface CrmTaskArtifact {
  kind: "crm_task";
  title: string;
  description: string;
  assignee?: string;
  due_date?: string; // ISO8601 date
  priority?: CrmTaskPriority;
}

// Message to post into a Slack channel or thread.
export interface SlackArtifact {
  kind: "slack";
  channel?: string;
  message: string;
}

// Discriminated union over the supported artifact shapes.
export type Artifact = EmailArtifact | CrmTaskArtifact | SlackArtifact;

// A single policy gate evaluated against a chosen action. `status` reports the
// gate outcome; `requires_approval` flags gates that hold the action for a
// human even when not strictly failing.
export type PolicyGateStatus = "pass" | "fail" | "warn" | string;

export interface PolicyGate {
  rule_id: string;
  description: string;
  status: PolicyGateStatus;
  detail: string;
  requires_approval?: boolean;
}

// ---------------------------------------------------------------------------
// Chat (generic agent console).
//
// A minimal transcript shape for the chat surface where a user can ask the
// platform to do anything and watch the tools it calls. ChatMessage is a single
// persisted turn; ChatToolCall is one tool invocation surfaced inline in an
// assistant turn's trace (tool name, the arguments it was called with, and a
// short human-readable result summary).
// ---------------------------------------------------------------------------

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatToolCall {
  tool: string;
  args?: Record<string, unknown>;
  summary?: string;
}
