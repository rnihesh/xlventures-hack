# Project guide for AI agents

Intelligent Next Best Action platform. Agentic decision intelligence: signals to explainable, confidence-scored next best actions, gated by human approval, improving via a learning loop.

Flagship domain: Customer Success / Churn. Engine is domain-agnostic via YAML domain packs.

## Stack

- Backend: Python (FastAPI), LangGraph orchestration, Postgres 17 + pgvector, asyncpg, Alembic, uv.
- Frontend: Next.js 15 (App Router), shadcn/ui, Tailwind.
- LLM: OpenAI (gpt-4.1 planner/critic, gpt-4.1-mini specialists, text-embedding-3-large).
- Eval: LangSmith, Ragas, DeepEval.

## Hard rules

- Do not use em dashes anywhere in code, comments, strings, or docs. Use commas, colons, or parentheses.
- Never override git identity. Use the global git config. Never add Co-Authored-By trailers.
- Commit messages: around 10 words or fewer, imperative, no body unless asked.
- Keep total commits well under 100, mid range. Group related work per commit.
- Do not commit plan or design docs. The `docs/` folder is gitignored. Only README, CLAUDE.md, AGENTS.md ship as markdown.
- Never commit secrets. `.env` is gitignored; keep `.env.example` current.

## Layout (target)

```
backend/      FastAPI + LangGraph, memory, retrieval, eval, domain pack loader
frontend/     Next.js + shadcn
contracts/    Shared OpenAPI + event + recommendation JSON schemas
domain_packs/ YAML domain configs (data, not code)
infra/        docker-compose, Dockerfiles
docs/         Local plans only (gitignored)
```

Full build plan lives at `docs/PLAN.md` (local, not committed).
