# Intelligent Next Best Action: Agentic Decision Intelligence Platform

XLVentures Hackathon · Project 2 (selected).

A domain-agnostic agentic decision engine that turns raw business signals into **explainable, confidence-scored Next Best Actions**, gated by human-in-the-loop approval and getting measurably smarter every time a human says yes or no.

- **Flagship domain:** Customer Success / Churn (engine is domain-agnostic via YAML Domain Packs).
- **Orchestration:** LangGraph (dynamic planner + specialist agents, durable checkpointing, HITL interrupts, memory store).
- **Stack:** Python FastAPI · Postgres 17 + pgvector · Next.js 15 (App Router) · shadcn/ui · OpenAI.

## Status

Planning complete. Build in progress.

## Deliverables

- 5-minute demo video
- 5-minute architecture walkthrough
- This repository (source + docs + setup)

## Repo layout (planned)

```
backend/        FastAPI + LangGraph orchestration, memory, retrieval, eval
frontend/       Next.js + shadcn UI
contracts/      Shared OpenAPI + event + recommendation JSON schemas
domain_packs/   YAML domain configs (data, not code)
infra/          docker-compose, Dockerfiles
docs/           PLAN.md and design docs
```

See `docs/PLAN.md` for the phased build roadmap.
