# Architecture

## What it is

The Intelligent Next Best Action (NBA) platform is an agentic decision intelligence system that turns raw account signals into explainable, confidence-scored next best actions, gated by human approval and improving through a learning loop. It solves a recurring problem in revenue and operations teams: people drown in dashboards and alerts but still have to decide what to actually do next, justify it, and execute it. The platform closes that gap by reasoning over signals with a team of LLM agents, grounding every recommendation in cited evidence, ranking alternatives with confidence, and enforcing policy before anything is sent. The flagship domain is Customer Success and churn, but the engine is domain-agnostic: behavior is configured by YAML domain packs (data, not code), so the same system retargets to collections, SaaS sales, or any other playbook-driven workflow.

## What it does

End-to-end flow for a single decision:

1. Signal: an at-risk account surfaces (usage drop, sentiment decline, missed milestone, payment risk). Signals are typed and defined per domain pack.
2. Planner: a LangGraph-orchestrated planner agent (gpt-4.1 class) reads the account context and signals, then decomposes the problem and routes work to the right specialists.
3. Specialist agents: risk scorer, retrieval agent, play recommender, outcome simulator, drafter, and critic each contribute a focused step (score the risk, pull evidence, propose plays, simulate outcomes, draft the artifact, and critique the result).
4. Retrieval with citations: the retrieval agent runs hybrid (vector plus lexical) search over the knowledge base in pgvector and attaches inline citations so every claim traces back to a source chunk.
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
    UI["Inbox / Run / Accounts / Domains / Learning / Eval"]
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
    EV["Eval (LangSmith, Ragas, DeepEval)"]
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

```mermaid
flowchart LR
  ST(["Signal in"]) --> PLAN["planner"]
  PLAN --> RET["retrieval"]
  RET --> RISK["risk_scorer"]
  RISK --> REC["play_recommender"]
  REC --> SIM["outcome_simulator"]
  SIM --> DRAFT["drafter"]
  DRAFT --> CRIT["critic"]
  CRIT -->|fails checks| PLAN
  CRIT -->|ok| POL["policy_gate"]
  POL -->|requires approval| HITL{{"HITL interrupt"}}
  POL -->|clear| COMMIT["commit"]
  HITL -->|approve / edit| COMMIT
  HITL -->|reject| STOP(["stop"])
  COMMIT --> STOP
  classDef accent fill:#D97757,stroke:#C2613F,color:#ffffff
  class PLAN,HITL accent
```

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

Backend (`backend/`): FastAPI app (`app/main.py`) exposing REST routes under `app/api/` (accounts, runs, domains, policy, execute, whatif, learning, eval, health). LangGraph orchestration lives in `app/graph/` (planner, state, instrumentation). Specialist agents live in `app/agents/` (risk_scorer, retrieval_agent, play_recommender, outcome_simulator, drafter, critic). Retrieval (`app/retrieval/`) does hybrid vector plus lexical search with chunking, embeddings, and citation assembly against pgvector. Memory (`app/memory/`) stores and distills episodes for the learning loop. Policy, explanation, and action generation live in `app/policy`, `app/explain/`, and `app/actions/`. Domain packs load via `app/packs/` (loader, registry, schema). Persistence uses asyncpg with Alembic migrations (`app/repositories/`, `alembic/`). Evaluation hooks into LangSmith, Ragas, and DeepEval.

Frontend (`frontend/`): Next.js 16 (App Router) with the Geist typeface and a restrained grayscale plus Claude-orange accent UI, built with shadcn-style components and Tailwind. App routes mirror the workflow: `inbox`, `run`, `accounts`, `domains`, `learning`, `eval`. Anything using hooks, state, or EventSource streaming is a client component.

Data: Postgres 17/18 with the pgvector extension holds accounts, runs, recommendations, episodes, and embedded knowledge chunks. Domain behavior is data: `domain_packs/*.yaml` define personas, signals, plays, policy, and retrieval scope. Shared contracts (`contracts/`) pin the OpenAPI surface, event schema, and recommendation JSON schema across backend and frontend.

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
| Evaluation | LangSmith, Ragas, DeepEval |
| Frontend | Next.js 16 (App Router), React 19 |
| UI | shadcn-style components, Tailwind, Geist, grayscale + Claude-orange |
| Domain config | YAML domain packs (`domain_packs/`) |
| Contracts | OpenAPI + JSON schemas (`contracts/`) |
| Infra | docker-compose, Dockerfiles (`infra/`) |

Note: the backend ships a deterministic offline mode (`DEMO_MODE`) so the full flow runs reproducibly without any API keys.

## How to start

Prerequisites:

- uv (Python package and project manager)
- Node 20 or newer
- Postgres 17 or 18 with the pgvector extension available

Environment (`.env` at repo root, copy from `.env.example`):

- `OPENAI_API_KEY`: OpenAI key (leave blank to run deterministic offline mode)
- `DATABASE_URL`: e.g. `postgresql://nba:nba@localhost:5432/nba`
- `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`: optional eval tracing
- `NEXT_PUBLIC_API_URL`: frontend to backend URL, e.g. `http://localhost:8000`
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
# Terminal 1: backend API on http://localhost:8000
cd backend && uv run --env-file ../.env uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend on http://localhost:3000
cd frontend && npm install && npm run dev
```

Convenience targets are in the `Makefile`: `make install`, `make api`, `make demo` (forced deterministic offline mode), `make seed`, `make migrate`, `make test`, `make eval`. The whole stack can also run via `make dev` (docker compose). Interactive API docs are at `http://localhost:8000/docs`.

## How to use

1. Open the app at `http://localhost:3000`.
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

- Domain packs (YAML): the primary extension surface. A pack in `domain_packs/` defines personas, signals, plays, policy, and retrieval scope. Shipping a new pack retargets planning, retrieval, decisioning, and explanation without touching code. Packs ship today for customer success, collections, and SaaS sales.
- Agent and tool registry: specialists in `app/agents/` and packs in `app/packs/` are registered and composed by the LangGraph planner, so new agents or tools slot into the graph without rewriting orchestration.
- Connectors: signals in and artifacts out are contract-driven (`contracts/`: OpenAPI, event schema, recommendation schema), so new source systems and execution targets attach by conforming to the schemas rather than by changing the core engine.

## 5-minute demo script

A beat-by-beat runbook for the recorded demo. Boot deterministic offline mode first (`make demo`, then `cd frontend && npm run dev`) so every number below reproduces exactly. The right column ties each beat to the judging rubric.

| Time | On screen | Say this | Rubric criterion |
| --- | --- | --- | --- |
| 0:00 | Inbox at `http://localhost:3000`, accounts ranked by risk. | "Operators drown in dashboards. This is a decision inbox: accounts ranked by churn risk and signal recency, not another alert feed. Northwind Logistics is critical, health 42, usage down 38 percent." | Use case: real pain, operator-ready. |
| 0:30 | Open Northwind Logistics (`ACC-1001`). | "Here is what the engine sees before it reasons: typed signals (usage drop, champion left, integration error) and account history. This is the raw context, not a recommendation yet." | Explainability: grounded inputs. |
| 0:50 | Click Run, the trace streams over SSE. | "One click starts a LangGraph run. Watch the live trace: the planner reads the signals and decides which specialists to call. This is a real plan per request, not a single prompt." | Agentic orchestration: dynamic planner. |
| 1:20 | Trace fills with specialist + tool-call steps. | "The planner dispatches the risk scorer, then retrieval runs a hybrid vector plus lexical search over pgvector, then the play recommender, outcome simulator, drafter, and critic each add a step. Every tool call is timestamped in the trace." | Agentic orchestration: composed specialists. |
| 1:50 | Recommendation card lands: primary NBA + confidence dial. | "The Next Best Action lands with a calibrated confidence score and a plain-language rationale. Nothing is a black box: this is why, in words a stakeholder can audit." | Explainability and trust. |
| 2:20 | Expand evidence citations. | "Every claim cites its source chunk with a character span. Click a citation and it traces back to the precedent document. The reasoning is grounded, not invented." | Explainability: cited evidence. |
| 2:40 | Expand ranked alternatives with why-not. | "It is a ranked slate, not one answer. Each alternative shows its tradeoff and why it was not chosen, so the human stays in control of the call." | Explainability: ranked alternatives. |
| 3:00 | Show what-we-still-need-to-know and policy gates. | "The card is honest about its blind spots: here is what it still does not know. And here is the policy gate: this action is held behind approval because it crosses a value threshold." | Trust: guardrails and humility. |
| 3:20 | Approve or edit at the HITL interrupt. | "The run paused at a human-in-the-loop interrupt via durable checkpointing. I can edit the draft or approve. I will tweak one line, then approve. My edit is captured as signal." | Agentic orchestration: HITL, human control. |
| 3:50 | One-click execute, artifact preview. | "Approving executes the action and generates the concrete artifact: a ready-to-send outreach email. Preview it before it ships." | Use case: one-click execution. |
| 4:10 | Record outcome, run learning distill, refresh `/eval`. | "I record the downstream outcome. The system distills my decision, my edit, and that outcome into a reusable lesson, then biases future planning. Watch the eval score move: improvement is measured, not claimed." | Learning: closed feedback loop, rigor. |
| 4:40 | Domains view, swap pack to Collections. | "Same engine, zero code change. I swap the YAML domain pack to Collections and the planner, retrieval, policy, and explanation all retarget. Customer Success, SaaS Sales, and Collections all ship today." | Extensibility: domain-agnostic by config. |
| 5:00 | Back to inbox. | "Signals to an explainable, confidence-scored action, gated by a human, getting smarter every loop. That is the platform." | Wrap: full thesis. |

## 5-minute architecture walkthrough script

A time-stamped narration of the design decisions, walking the mermaid diagrams already in this file. Open the doc and scroll as you speak.

| Time | Reference | Narrate the decision |
| --- | --- | --- |
| 0:00 | "System overview" diagram. | "The thesis: turn signals into explainable, confidence-scored next best actions, gated by a human, improving on a loop. Three planes: a Next.js frontend, a FastAPI plus LangGraph backend, and Postgres with pgvector. The orange nodes, planner and explanation, are where the value concentrates." |
| 0:40 | "Agent orchestration (LangGraph)" diagram. | "Why LangGraph and not one big prompt: decisions need a plan. The planner composes specialists (risk scorer, retrieval, play recommender, outcome simulator, drafter, critic) as graph nodes. The critic can loop back to replan on failed checks. This is auditable, debuggable orchestration with a typed state, not a chat transcript." |
| 1:30 | "Retrieval and learning loop" diagram (ingest and query). | "Why pgvector hybrid retrieval: trust requires citation. Documents are contextually chunked with character spans, embedded (OpenAI 1536-d, deterministic hash fallback offline), and indexed with HNSW. Queries combine vector cosine and lexical search, so every recommendation cites ranked chunks back to an exact source span. Evidence, not vibes." |
| 2:20 | "Retrieval and learning loop" diagram (learn subgraph). | "Why a memory and learning loop: a decision tool that does not learn is a calculator. Every approval, edit, rejection, and downstream outcome is written as an episode, distilled into preferences, and fed back into retrieval and planning. The system compounds: tomorrow's recommendation is shaped by today's outcome." |
| 3:00 | "Decision lifecycle" sequence diagram (policy gate and HITL). | "Why a policy gate plus human-in-the-loop: autonomy without guardrails is a liability. Candidate actions are checked against domain policy (channels, value limits, approval thresholds) before a human sees them. LangGraph durable checkpointing pauses the run at the interrupt and resumes on approval or edit. The human is the commit step, always." |
| 3:40 | "System overview" diagram (PACKS config edges). | "Why domain packs: the engine is domain-agnostic. Personas, signals, plays, policy, and retrieval scope are YAML data, not code. The same graph retargets from Customer Success to Collections to SaaS Sales by loading a different pack. Reuse is a config edge, not a rewrite." |
| 4:20 | Eval node on the "System overview" diagram. | "Why an eval harness: claims need proof. A golden-scenario harness (LangSmith, Ragas, DeepEval) scores recommendation quality across components and outcomes, so every change is measured. Plus offline-deterministic fallbacks, shared contracts, and Alembic migrations make the whole thing reproducible on any laptop." |
| 4:50 | Tech stack table. | "Freedom to Innovate, exercised deliberately: LangGraph for durable agentic orchestration, pgvector for cited retrieval, FastAPI plus SSE for live traces, Next.js 16 and React 19 for the inbox. Every choice serves explainability, trust, and the learning loop." |
