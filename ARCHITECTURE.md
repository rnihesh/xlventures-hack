# Architecture

## What it is

The Intelligent Next Best Action (NBA) platform is an agentic decision intelligence system that turns raw account signals into explainable, confidence-scored next best actions, gated by human approval and improving through a learning loop. It solves a recurring problem in revenue and operations teams: people drown in dashboards and alerts but still have to decide what to actually do next, justify it, and execute it. The platform closes that gap by reasoning over signals with a team of LLM agents, grounding every recommendation in cited evidence, ranking alternatives with confidence, and enforcing policy before anything is sent. The flagship domain is Customer Success and churn, but the engine is domain-agnostic: behavior is configured by YAML domain packs (data, not code), so the same system retargets to collections, SaaS sales, or any other playbook-driven workflow.

## What it does

End-to-end flow for a single decision:

1. Signal: an at-risk account surfaces (usage drop, sentiment decline, missed milestone, payment risk). Signals are typed and defined per domain pack.
2. Planner: a LangGraph-orchestrated planner agent (gpt-4.1 class) reads the account context and signals, then decomposes the problem and routes work to the right specialists.
3. Specialist agents: retrieval agent, risk scorer, gap analysis, play recommender, outcome simulator, drafter, and critic each contribute a focused step (pull evidence, score the risk, flag missing information, propose plays, simulate outcomes, draft the artifact, and critique the result). Gap analysis and critic always run; the planner gates the rest by roster.
4. Retrieval with citations: the retrieval agent runs hybrid (vector plus lexical) search over the knowledge base in pgvector and attaches inline citations so every claim traces back to a source chunk. Gap analysis can loop back to retrieval when grounding is thin, and the critic can trigger a bounded replan to retrieval or the play recommender.
5. Policy gate: candidate actions are checked against domain policy (allowed channels, guardrails, approval thresholds, value limits). Violations are blocked or flagged before a human ever sees them.
6. Explainable recommendation: the system emits a structured recommendation with a primary action, ranked alternatives, a confidence score, the evidence citations, the simulated outcome, and the policy gates that passed or fired.
7. Human approval: a reviewer reads the explanation in the inbox and approves, edits, or rejects. Nothing executes without a human decision.
8. One-click execute: on approval the chosen action generates a concrete artifact (email draft, task, save play) ready to send or push.
9. Learning loop: the decision, edits, and downstream outcome are written back as episodes, distilled into memory, and fed into future retrieval and planning so the system gets better over time.

## Architecture

### System overview

```mermaid
flowchart TB
  subgraph FE["Frontend (Next.js 16, Geist, grayscale + Claude orange)"]
    UI["Inbox / Run / Accounts (tabbed 360) / Contacts / Copilot / Agents / Domains / Rules / Ingest / Learning / Eval"]
  end
  subgraph BE["Backend (FastAPI + LangGraph)"]
    API["REST API (OpenAPI contract, REST + SSE)"]
    PL["Planner agent"]
    subgraph SP["Specialist agents"]
      RS["Risk scorer"]
      RA["Retrieval agent"]
      PR["Play recommender"]
      OS["Outcome simulator"]
      DR["Drafter"]
      CR["Critic"]
    end
    PG2["Policy gate"]
    EX["Explain / recommendation"]
    AC["Actions / generators"]
    MEM["Memory / episodes"]
    EV["Eval (5 offline suites, optional LangSmith trace)"]
  end
  subgraph DATA["Data"]
    PGV[("Postgres 17/18 + pgvector")]
    PACKS["domain_packs/*.yaml (config)"]
  end

  UI -->|REST + SSE| API
  API --> PL
  PL --> RS & RA & PR & OS & DR & CR
  RA <--> PGV
  CR --> PG2 --> EX --> UI
  EX --> AC --> MEM
  MEM --> PL
  MEM <--> PGV
  EX -.metrics.-> EV
  PACKS -. config .-> PL
  PACKS -. config .-> PG2

  classDef accent fill:#D97757,stroke:#C2613F,color:#ffffff
  class PL,EX accent
```

### Decision lifecycle

```mermaid
sequenceDiagram
  participant S as Signal
  participant P as Planner
  participant A as Specialist agents
  participant R as Retrieval (pgvector)
  participant G as Policy gate
  participant H as Human reviewer
  participant E as Executor
  participant M as Memory
  S->>P: at-risk account + typed signals
  P->>A: decompose and route
  A->>R: hybrid search (vector + lexical)
  R-->>A: evidence chunks + citations
  A-->>P: risk, plays, simulated outcome, draft, critique
  P->>G: candidate actions
  G-->>P: pass / flag / block
  P->>H: explainable recommendation (ranked, confidence, citations)
  H->>E: approve or edit
  E-->>H: generated artifact (email, task, save play)
  H->>M: decision + downstream outcome
  M-->>P: distilled lessons feed future runs
```

### Agent orchestration (LangGraph)

The topology is fixed (every node is registered) but the edges are conditional: the planner's roster decides which specialists actually execute, and the clarify and replan loops decide when to revisit earlier nodes. Node names below match `app/graph/planner.py` exactly.

```mermaid
flowchart LR
  ST(["Signal in"]) --> PLAN["planner"]
  PLAN -->|selects roster| RET["retrieval"]
  RET --> RISK["risk_scorer"]
  RISK --> GAP["gap_analysis"]
  GAP -->|needs grounding| RET
  GAP --> REC["play_recommender"]
  REC --> SIM["outcome_simulator"]
  SIM --> DRAFT["drafter"]
  DRAFT --> CRIT["critic"]
  CRIT -->|replan: retrieval| RET
  CRIT -->|replan: recommender| REC
  CRIT -->|ok| POL["policy_gate"]
  POL --> HITL{{"hitl_gate"}}
  HITL -->|requires approval| WAIT(["HITL interrupt: approve / edit / reject"])
  HITL -->|auto-approve| COMMIT["commit"]
  WAIT --> COMMIT
  COMMIT --> STOP(["episode written"])
  classDef accent fill:#D97757,stroke:#C2613F,color:#ffffff
  class PLAN,HITL accent
```

The sequence the routers traverse is `retrieval, risk_scorer, gap_analysis, play_recommender, outcome_simulator, drafter, critic`; `gap_analysis` and `critic` are always on, the rest are gated by the planner's roster. The deterministic tail is `policy_gate -> hitl_gate -> commit`. The HITL interrupt is surfaced to the UI by the runs API based on the critic verdict, paused by LangGraph durable checkpointing and resumed on the human decision.

### Retrieval and learning loop

```mermaid
flowchart TB
  subgraph Ingest["Ingest"]
    DOCS["Seed + connector documents"] --> CHUNK["Contextual chunking (char spans)"]
    CHUNK --> EMB["OpenAI embeddings (1536-d), hash fallback offline"]
    EMB --> VEC[("document_chunks: vector(1536), HNSW index")]
  end
  subgraph Query["Query"]
    Q["Agent query"] --> HYB["Hybrid: vector cosine (&lt;=&gt;) + lexical"]
    VEC --> HYB
    HYB --> CITE["Ranked chunks + span citations"]
  end
  subgraph Learn["Learning loop"]
    DEC["Approve / edit / reject + outcome"] --> EPI["Episode written"]
    EPI --> DIST["Distill"]
    DIST --> PREF[("Memory / preferences")]
    PREF --> Q
  end
  classDef accent fill:#D97757,stroke:#C2613F,color:#ffffff
  class CITE,PREF accent
```

Backend (`backend/`): FastAPI app (`app/main.py`) exposing REST routes under `app/api/` (accounts, runs, domains, policy, execute, whatif, learning, eval, health). LangGraph orchestration lives in `app/graph/` (planner, state, instrumentation). Specialist agents live in `app/agents/` (retrieval_agent, risk_scorer, gap_analysis, play_recommender, outcome_simulator, drafter, critic) and are resolved from the agent registry (`app/packs/registry.py`) by capability. Retrieval (`app/retrieval/`) does hybrid vector plus lexical search with chunking, embeddings, and citation assembly against pgvector. Memory (`app/memory/`) stores and distills episodes for the learning loop. Policy, explanation, and action generation live in `app/policy`, `app/explain/`, and `app/actions/`. Domain packs load via `app/packs/` (loader, registry, schema). Persistence uses asyncpg with Alembic migrations (`app/repositories/`, `alembic/`). Evaluation (`app/eval/`) is a custom offline golden-scenario harness with optional LangSmith tracing.

### Evaluation methodology

The eval harness (`app/eval/`) runs the real planner graph over golden cases (`app/eval/golden.jsonl`) and scores five suites, all deterministic and computable fully offline (no external eval service required):

| Suite | Source | What it measures |
| --- | --- | --- |
| Citation Grounding | `component.py` | Every recommendation cites well-formed evidence with valid character spans |
| Retrieval Faithfulness | `component.py` | Each evidence claim is lexically supported by its cited source chunk |
| Action Match | `scenario.py` | The recommended action matches the expected action for the golden case |
| Trajectory Validity | `scenario.py` | The executed node path is a valid trajectory for the selected roster |
| Outcome Lift | `outcome.py` | Org-scoped business outcomes (at-risk ARR, win rate) move from the learning loop |

`runner.run_all(org_id)` aggregates the suites into the `/eval` contract shape, writes a cached snapshot to `_last_run.json`, and the Outcome Lift suite is scoped to the caller's org so the learning loop is measured per tenant. LangSmith tracing is optional and activates only when `LANGSMITH_TRACING` is set.

Frontend (`frontend/`): Next.js 16 (App Router) with the Geist typeface and a restrained grayscale plus Claude-orange accent UI, built with shadcn-style components and Tailwind. App routes mirror the workflow and platform surfaces: `inbox`, `run` (with a durable Recent-runs panel), `accounts` (a tabbed 360: Signals, Documents and context, Past runs, Timeline, What-if), `contacts`, `chat` (the agentic Copilot console), `agents` (the reusable agent and tool catalog), `domains` (with paste-a-pack upload), `rules` (the editable business-rules and action catalog), `ingest` (drop-to-ingest interactions), `learning`, `eval`, plus auth (`login`, `signup`, `verify`) and `settings`. Anything using hooks, state, or EventSource streaming is a client component.

Data: Postgres 17/18 with the pgvector extension holds accounts, runs, recommendations, episodes, and embedded knowledge chunks. Domain behavior is data: `domain_packs/*.yaml` define personas, signals, plays, policy, and retrieval scope. Shared contracts (`contracts/`) pin the OpenAPI surface, event schema, and recommendation JSON schema across backend and frontend.

### Policy and rules engine

Guardrails are a declarative layer (`app/policy/engine.py`, `app/policy/rules.py`), not hardcoded logic. Each rule is a few lines of YAML in a pack's `policy` section. Two machine-checkable rule types ship today: `action_requires_approval` (named actions always route to a human) and `field_threshold` (a candidate field compared with an operator and value, optionally forcing approval on violation); free-text guardrails are preserved as human-judgment notes. The `policy_gate` node evaluates every candidate against the effective rule set before a human ever sees it: violations block or flag the action, and a `requires_approval` hit forces the HITL route instead of an auto-approval. Orgs tailor rules and the action catalog from the UI via `GET/PUT /rules/{domain}`: edits persist as an additive override merged onto the intact base pack, so the planner and policy engine always read the *effective* pack for the current org.

### Memory and learning model

Memory (`app/memory/store.py`) stores decision episodes carrying `account_id`, `domain`, `situation`, `action_key`, the full recommendation, the downstream outcome, and `org_id`. The `commit` node writes an episode at the end of every run. `recall_similar` pulls precedent episodes (vector similarity, with an offline deterministic fallback) into retrieval and planning so a new decision is informed by what happened in similar past situations. `distill` (`app/memory/distill.py`) turns accumulated decisions, edits, rejections, and outcomes into reusable preferences and lessons that bias future planning and confidence. The loop is org-scoped: an org learns from its own history.

### Agentic Copilot, agent and tool registry

Every capability the REST API exposes is also a callable TOOL, so the platform ships an agentic Copilot (`app/chat/`), not a RAG chatbot. The same tool layer (`app/chat/tools.py`) drives two paths: real OpenAI tool-calling when a key is present, and a deterministic router offline. Tools include triage, account 360, run an NBA (the planner graph), search the knowledge base with citations, evaluate policy, generate and send artifacts, ingest interactions, and read learning and eval. The chat streams over SSE (`app/api/chat.py`): assistant tokens stream incrementally, each tool call emits running and result events, and a `thinking` event drives a live reasoning indicator. The reusable agent and tool architecture is itself a surface: `GET /agents` and `GET /tools` serialize the registry (`app/packs/registry.py`: capabilities, produced state keys, cost tier, governance metadata) into the Agents page, so adding a capability is a registration, not a graph rewrite. The Copilot is strictly scoped (declines off-topic asks) and grounded (it reports tool results verbatim, never inventing names or data).

### Persistence and durability

Tenant data is durable across restarts, not held in process memory. Accounts, contacts, integrations, pack overrides, chat sessions, and uploaded interaction chunks (`document_chunks`) persist in Postgres. Decision episodes persist to the episodes table and the memory store hydrates them from the database on startup (`app/main.py` lifespan), so the learning loop, the account 360 (durable Documents and Past-runs tabs), the timeline, and the `/runs` history all read durable storage. Uploaded files (crm-notes, transcripts, emails) survive restarts because their chunks live in pgvector and the 360 reads them from there. The in-memory run registry is a live-session convenience layered over the durable episode history.

### Multi-tenant data model

Every request resolves a tenant from an httpOnly `nba_session` JWT cookie: `get_current_user` validates the token and `get_current_org` (exposed as the `current_org` dependency) yields the caller's `org_id`. Org-owned rows (accounts, contacts, episodes, integrations, and pack overrides) carry `org_id` and are filtered by it, so tenants never see each other's data; seeded day-zero data belongs to a `DEMO_ORG` default. Authentication is handled by signup and login (issuing the JWT) with Google as an optional sign-in method (`app/services/google_oauth.py`). Outbound connectors are per-org: AWS SES email (`app/services/email.py`), a Slack incoming webhook (`app/services/slack.py`), and Google, all configured and stored per org through `/integrations` and all offline-safe (a missing or unconfigured connector degrades to a no-op result rather than raising).

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend framework | Python, FastAPI |
| Orchestration | LangGraph |
| Database | Postgres 17/18 + pgvector |
| DB access | asyncpg, Alembic migrations |
| Python tooling | uv (project and venv management) |
| LLM | OpenAI (gpt-4.1 planner/critic, gpt-4.1-mini specialists, text-embedding-3-large) |
| Retrieval | Hybrid vector (pgvector) plus lexical, inline citations |
| Evaluation | Custom offline golden-scenario harness (5 suites), optional LangSmith tracing |
| Frontend | Next.js 16 (App Router), React 19 |
| UI | shadcn-style components, Tailwind, Geist, grayscale + Claude-orange |
| Domain config | YAML domain packs (`domain_packs/`) |
| Contracts | OpenAPI + JSON schemas (`contracts/`) |
| Infra | docker-compose, Dockerfiles (`infra/`) |

Note: there is no `DEMO_MODE` toggle. With an `OPENAI_API_KEY` set the app always uses the real model; with no key (CI / tests) it falls back to a deterministic offline model so the full flow still runs reproducibly without spending tokens.

## How to start

Prerequisites:

- uv (Python package and project manager)
- Node 20 or newer
- Postgres 17 or 18 with the pgvector extension available

Environment (`.env` at repo root, copy from `.env.example`):

- `OPENAI_API_KEY`: OpenAI key (set for the real model; leave blank only for offline tests, where a deterministic model is used)
- `DATABASE_URL`: e.g. `postgresql://nba:nba@localhost:5432/nba`
- `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`: optional eval tracing
- `NEXT_PUBLIC_API_URL`: frontend to backend URL, e.g. `http://localhost:8200`
- `APP_ENV`: `dev`
- `APP_TOKEN`: optional; when set, run endpoints require `Authorization: Bearer <APP_TOKEN>`. Leave blank for open demo mode.

Postgres + pgvector setup:

1. Create the database and role, then enable the extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
2. Point `DATABASE_URL` in `.env` at that database (e.g. `postgresql://nba:nba@localhost:5432/nba`).
3. Apply schema migrations:
   ```bash
   cd backend && uv run alembic upgrade head
   ```
4. Ingest and seed data (loads domain packs, accounts, and embedded knowledge chunks):
   ```bash
   cd backend && uv run --env-file ../.env python -m app.seed
   ```

Two-command local run:

```bash
# Terminal 1: backend API on http://localhost:8200
cd backend && uv run --env-file ../.env uvicorn app.main:app --reload --port 8200

# Terminal 2: frontend on http://localhost:3200
cd frontend && npm install && npm run dev
```

Convenience targets are in the `Makefile`: `make install`, `make api`, `make seed`, `make migrate`, `make test` (runs offline with a blank key), `make eval`, `make gen-runs` (seed learning episodes). The whole stack can also run via `make dev` (docker compose). Interactive API docs are at `http://localhost:8200/docs`.

## How to use

1. Open the app at `http://localhost:3200`.
2. In the inbox, pick an at-risk account (the list is ranked by risk and signal recency).
3. Run an NBA: the planner and specialist agents execute and the result streams into the run view.
4. Read the explainable recommendation:
   - Evidence citations: each claim links back to its source chunk.
   - Ranked alternatives: the primary action plus scored fallbacks.
   - Confidence: a calibrated score for the recommendation.
   - Policy gates: which guardrails passed or fired, and why.
5. Approve, edit, or reject. Edits are captured; nothing executes without your decision.
6. Execute the artifact: one click generates the concrete output (email draft, task, save play) ready to send or push.
7. Watch the learning loop: the decision, your edits, and the outcome become episodes that are distilled into memory and inform future runs (visible in the learning view).
8. Retarget the domain: switch the active domain pack (`domain_packs/*.yaml`, surfaced in the domains view) to point the same engine at collections, SaaS sales, or your own playbook with no code changes.

## Reuse and extensibility

- Domain packs (YAML): the primary extension surface. A pack in `domain_packs/` defines personas, signals, plays, policy, decision-point rosters, and action economics. Shipping a new pack retargets planning, retrieval, decisioning, and explanation without touching code. Packs ship today for customer success, collections, and SaaS sales, and an org can paste a new pack from the Domains UI (validated against the schema, stored as an org pack) and run a decision on it in under a minute.
- Configurable business rules: the policy guardrails and action catalog are editable per org from the Rules page (`GET/PUT /rules/{domain}`), persisted as an additive override merged onto the intact base pack.
- Agent and tool registry: specialists in `app/agents/` and packs in `app/packs/` are registered and composed by the LangGraph planner, exposed read-only via `GET /agents` and `GET /tools` and the Agents page, so new agents or tools slot into the graph without rewriting orchestration.
- Connectors: signals in and artifacts out are contract-driven (`contracts/`: OpenAPI, event schema, recommendation schema), so new source systems and execution targets attach by conforming to the schemas rather than by changing the core engine.
