# Intelligent Next Best Action

**Turn raw business signals into explainable, confidence-scored Next Best Actions that a human approves in one click, and that get measurably smarter every time.**

XLVentures Hackathon, Project 2 (selected).

## The problem

Operators drown in dashboards but starve for decisions. A Customer Success Manager can see that an account is slipping, yet still has to guess what to do, justify it to a skeptical stakeholder, and hope it works. Most "AI" tools stop at a prediction or a chat reply: no ranked options, no reasoning a human can audit, no guardrails, and no memory of what actually worked last time.

Project 2 asks for an agentic decision engine. We built a domain-agnostic one. It ingests signals, plans a strategy, runs specialist agents, retrieves precedent, scores confidence, enforces policy, and proposes a **Next Best Action** with ranked alternatives and a plain-language rationale. A human approves or rejects, the action executes, the outcome is recorded, and the system distills that feedback into reusable lessons. The flagship domain is Customer Success and churn, but the engine specializes to any vertical through YAML Domain Packs (data, not code).

## Architecture overview

```
                 Signals + account context
                            |
                    +---------------+
                    |    Planner    |   dynamic strategy, picks specialists
                    +---------------+
                            |
        +-------------------+-------------------+
        |          |            |               |
   +---------+ +---------+ +-----------+ +--------------+
   | Risk    | | Action  | | Retrieval | | Explanation  |   specialist agents
   | analyst | | drafter | | precedent | | + rationale  |
   +---------+ +---------+ | + vectors | +--------------+
        |          |       +-----------+        |
        +-------------------+-------------------+
                            |
                  +---------------------+
                  | Policy / guardrails |   hard limits, approval thresholds
                  +---------------------+
                            |
                  +---------------------+
                  | Recommendation:     |   NBA + ranked alternatives
                  | NBA + confidence    |   + confidence + explanation
                  +---------------------+
                            |
                  Human-in-the-loop approval (HITL interrupt)
                            |
                  +---------------------+
                  | One-click execute   | -> outcome recorded
                  +---------------------+
                            |
                  +---------------------+
                  | Learning loop       |   distill yes/no + outcomes into
                  | (memory store)      |   reusable lessons and priors
                  +---------------------+
```

- **Planner + specialist agents:** a LangGraph orchestrator builds a plan per request and dispatches specialist nodes (risk analysis, action drafting, retrieval, explanation). Durable checkpointing lets a run pause at a human-approval interrupt and resume later.
- **Memory and learning:** approvals, rejections, and downstream outcomes are stored and distilled into lessons that bias future planning and confidence scoring.
- **Retrieval:** precedent and policy context are pulled from a pgvector store (with a deterministic in-memory fallback offline) so recommendations cite similar past situations.
- **Policy:** a guardrail layer evaluates each candidate against domain limits and approval thresholds before it is ever shown.
- **Eval:** a golden-scenario harness scores recommendation quality across components and outcomes, so changes are measured, not guessed.

## Key features

- **Explainable recommendations:** every NBA ships with a plain-language rationale, the signals that drove it, and a calibrated confidence score.
- **Ranked alternatives:** not one answer but a ranked slate, each with its own tradeoffs, so the human stays in control.
- **Counterfactual what-if:** adjust a signal or assumption and re-score instantly to see how the recommendation would change.
- **Learning loop:** human yes/no plus real outcomes are distilled into reusable lessons that move future confidence and ranking.
- **Guardrails:** policy evaluation enforces hard limits and approval thresholds; risky actions require sign-off.
- **One-click execution:** approve to execute, with the artifact (for example a drafted outreach) previewed before it goes out.
- **Multi-domain packs:** swap the YAML Domain Pack to retarget the engine (Customer Success, SaaS Sales, Collections shipped) with no code changes.

## Tech stack

| Layer | Choice |
| --- | --- |
| Orchestration | LangGraph (planner, specialist agents, checkpointing, HITL interrupts, memory store) |
| Backend | Python 3.12, FastAPI, Uvicorn, SSE streaming |
| Data | Postgres 17 + pgvector (with offline deterministic fallback) |
| LLM | OpenAI via langchain-openai (with offline deterministic fallback) |
| Frontend | Next.js 15 (App Router), React 19, Tailwind, shadcn-style UI, lucide icons |
| Contracts | Shared OpenAPI + JSON Schemas in `contracts/` |
| Domain config | YAML Domain Packs in `domain_packs/` |
| Infra | Docker Compose, Alembic migrations |

**Offline first:** the whole system runs with no `OPENAI_API_KEY` and no `DATABASE_URL`. Missing services fall back to deterministic stubs so the demo and tests are reproducible on any laptop.

## Repo layout

```
backend/        FastAPI + LangGraph orchestration, memory, retrieval, policy, eval
frontend/       Next.js + shadcn-style UI
contracts/      Shared OpenAPI + event + recommendation JSON schemas
domain_packs/   YAML domain configs (data, not code)
infra/          docker-compose, Dockerfiles
docs/           PLAN.md and design docs
```

## How to run

Config lives in a single root `.env` (already templated in `.env.example`). Every value is optional: with all blanks the app runs fully offline with deterministic stubs (no OpenAI key, no database). Copy the template if you do not already have a `.env`:

```bash
cp .env.example .env
```

### Quickstart (two terminals)

```bash
# terminal 1: backend (loads ./.env, http://localhost:8000)
make install        # cd backend && uv sync --extra dev
make api            # live mode (uses OPENAI_API_KEY if set, else offline)
#   or: make demo   # forced deterministic DEMO_MODE for recording the demo

# terminal 2: frontend (http://localhost:3000)
cd frontend && npm install && npm run dev
```

Open http://localhost:3000. The backend env (including `DEMO_MODE`, `APP_TOKEN`, `DATABASE_URL`) is loaded from `./.env` via `uv run --env-file`. The frontend reads `NEXT_PUBLIC_API_URL` from `frontend/.env.local`.

One-command alternative (Docker): `make dev` brings up Postgres + pgvector, the API, and the web app together, reading the same root `.env`.

### Backend (uv)

The backend is a [uv](https://docs.astral.sh/uv/) project (dependencies pinned in `backend/uv.lock`).

```bash
cd backend
uv sync                                  # create .venv and install from the lockfile
uv run uvicorn app.main:app --reload --port 8000
```

`uv sync` installs runtime deps; add `--extra dev` for tests and tooling. Any `uv run <cmd>` executes inside the managed environment, so no manual venv activation is needed.

The API serves on http://localhost:8000 (interactive docs at `/docs`).

### Frontend (npm)

```bash
cd frontend
npm install
npm run dev
```

The UI serves on http://localhost:3000 and talks to the API at `NEXT_PUBLIC_API_URL`.

### Docker Compose (one command)

Brings up Postgres + pgvector, the API, and the web app together:

```bash
make dev      # docker compose -f infra/docker-compose.yml up
make down     # tear everything down
make migrate  # apply Alembic migrations inside the api container
```

### Environment

All configuration lives in `.env` (see `.env.example`):

- `OPENAI_API_KEY` (optional): blank uses the deterministic LLM fallback.
- `DATABASE_URL` (optional): blank runs DB-less with in-memory stores.
- `NEXT_PUBLIC_API_URL`: where the frontend reaches the API.
- `APP_TOKEN` (optional): when set, execution endpoints require `Authorization: Bearer <APP_TOKEN>`; blank keeps open demo mode.
- `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`: optional tracing.

## How to seed

```bash
make seed     # cd backend && uv run python -m app.seed
```

Loads demo accounts, signals, and precedent for the flagship Customer Success domain so the UI has something to recommend against immediately.

## Tests and eval

```bash
# unit + integration tests
cd backend && uv run pytest      # or: make test

# recommendation quality eval (golden scenarios)
make eval     # cd backend && uv run python -m app.eval.runner
```

The eval harness scores components and outcomes against `backend/app/eval/golden.jsonl` and writes the latest run summary to `backend/app/eval/_last_run.json`. Both tests and eval run fully offline.

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness check |
| POST | `/runs` | Start a decision run for an account or signal set |
| GET | `/runs/{run_id}/stream` | Stream planner + agent steps and the final recommendation (SSE) |
| POST | `/runs/{run_id}/hitl` | Approve or reject at the human-in-the-loop interrupt |
| GET | `/accounts` | List accounts |
| GET | `/accounts/{account_id}` | Account detail with signals and history |
| GET | `/domains` | List installed Domain Packs |
| GET | `/domains/{domain_key}` | Domain Pack detail |
| POST | `/whatif` | Counterfactual re-scoring of a recommendation |
| GET | `/policy/{domain}` | Policy and guardrails for a domain |
| POST | `/policy/evaluate` | Evaluate a candidate action against policy |
| POST | `/execute` | Execute an approved action |
| GET | `/execute/{run_id}` | Execution status and artifact |
| GET | `/learning` | Distilled lessons and learning state |
| POST | `/learning/distill` | Distill recent feedback into lessons |
| POST | `/learning/outcome` | Record a downstream outcome |
| GET | `/eval` | Latest eval run summary |

The full contract lives in `contracts/openapi.json`, with recommendation and event shapes in `contracts/recommendation.schema.json` and `contracts/events.schema.json`.

## Demo walkthrough

A tight 5-minute story, fully offline and deterministic. One command boots the API with `DEMO_MODE=1`:

```bash
make demo      # backend on http://localhost:8000 (deterministic, no API keys)
```

Then in another terminal start the UI (`cd frontend && npm install && npm run dev`, http://localhost:3000). Every API call below also lives as a ready-to-run example in `scripts/requests.http` (VS Code REST Client, JetBrains, or curl).

1. **Open the inbox.** The accounts list surfaces an at-risk account: Northwind Logistics (`ACC-1001`), health 42, usage down 38 percent after an integration broke and the champion left.
2. **Run the engine.** Kick off a run on that account and watch the trace stream: the planner picks specialists, risk analysis scores the threat, the drafter proposes an action, retrieval cites a similar past account.
3. **Read the explainable NBA.** The Next Best Action lands with a confidence dial, a plain-language rationale, cited evidence, ranked alternatives, and the policy gates that must clear before it can ship.
4. **Approve and execute.** Clear the human-in-the-loop interrupt with one click, preview the drafted artifact (email, CRM task, or Slack), and execute.
5. **Show the learning improvement.** Record the outcome and distill it into a lesson, then refresh `/eval` to see the score move.
6. **Swap the domain pack.** Switch to SaaS Sales or Collections to prove the same engine retargets with zero code changes.

## Five-minute demo script

1. **Setup (30s).** `cp .env.example .env`, then `make seed`. Start the backend (`uvicorn app.main:app --port 8000`) and frontend (`npm run dev`). Open http://localhost:3000. No API keys needed.
2. **Pick an at-risk account (45s).** Open an account showing a usage drop. Point out the signals and history the engine sees.
3. **Run the engine (60s).** Trigger a run and watch the trace stream: planner picks specialists, risk analysis scores the threat, the drafter proposes an action, retrieval cites a similar past account. The Next Best Action lands with a confidence dial and a plain-language rationale.
4. **Show alternatives and what-if (60s).** Expand the ranked alternatives. Open the what-if panel, lower the usage signal, and watch confidence and ranking shift in real time.
5. **Guardrails, approve, execute (60s).** Note the policy panel gating the action behind approval. Approve it; preview the drafted artifact; execute with one click.
6. **Close the loop (45s).** Record the outcome, run the learning distill, and show the new lesson plus a refreshed eval score. Then switch the Domain Pack to SaaS Sales to prove the same engine retargets with zero code changes.

## How this maps to the judging rubric

**Platform (70 percent)**

- *Agentic orchestration:* a real planner that composes specialist agents per request, with durable checkpointing and human-in-the-loop interrupts (LangGraph), not a single prompt.
- *Explainability and trust:* every recommendation carries confidence, rationale, cited precedent, and ranked alternatives; guardrails gate risky actions.
- *Learning:* a closed feedback loop distills approvals, rejections, and outcomes into reusable lessons that measurably move future decisions.
- *Reliability and rigor:* offline-deterministic fallbacks, shared contracts, Alembic migrations, a golden-scenario eval harness, and CI on every push.
- *Extensibility:* Domain Packs make the platform domain-agnostic by configuration, demonstrated across three verticals.

**Use case (30 percent)**

- *Real pain, real stakes:* churn and net revenue retention are board-level metrics; faster, defensible, learning-backed decisions directly protect revenue.
- *Operator-ready:* one-click execution with artifact preview and counterfactual what-if fits the daily workflow of a Customer Success Manager.
- *Generalizable:* the same flow already serves SaaS Sales and Collections, showing the use case is a wedge, not a ceiling.

## Deliverables

- Five-minute demo video
- Five-minute architecture walkthrough
- This repository (source, docs, setup)

See `docs/PLAN.md` for the phased build roadmap.
