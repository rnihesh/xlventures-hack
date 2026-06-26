# nba-backend

Next Best Action backend: FastAPI + LangGraph explainable recommendations.

This package (`app/`) exposes a FastAPI application served by uvicorn
(`uvicorn app.main:app`). Database schema is managed with Alembic.

## Local development

```bash
cd backend
pip install -e .[dev]      # install the package and dev tooling
uvicorn app.main:app --reload
```

## Database migrations

```bash
alembic upgrade head       # apply migrations (reads DATABASE_URL via app.config)
```

## Container / compose

The service is built from `infra/Dockerfile.api` (build context `./backend`) and
orchestrated via `infra/docker-compose.yml`. See the repository root `README.md`
for the full stack workflow (`make dev`, `make migrate`, `make seed`, `make eval`).

Configuration is read from environment variables (see `.env.example` at the repo
root). All external calls have deterministic offline fallbacks so the stack runs
without secrets.
