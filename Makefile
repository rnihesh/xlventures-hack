.PHONY: dev demo down install api test seed eval gen-runs migrate fmt

install:
	cd backend && uv sync --extra dev

# Run the API with whatever is configured in ./.env (real OpenAI key if set,
# otherwise deterministic offline mode).
api:
	cd backend && uv run --env-file ../.env uvicorn app.main:app --reload --port 8200

# Run the API forced into deterministic DEMO_MODE (reproducible, offline).
demo:
	@echo "Booting Intelligent NBA backend in DEMO_MODE (deterministic, offline, no API keys)..."
	@echo ""
	@echo "  API:       http://localhost:8200"
	@echo "  Docs:      http://localhost:8200/docs  (interactive OpenAPI)"
	@echo "  Health:    http://localhost:8200/health"
	@echo "  Requests:  scripts/requests.http  (curl / REST-client examples for every endpoint)"
	@echo ""
	@echo "  Frontend:  in another terminal run 'cd frontend && npm install && npm run dev' (http://localhost:3200)"
	@echo ""
	cd backend && OPENAI_API_KEY= uv run --env-file ../.env uvicorn app.main:app --port 8200

dev:
	docker compose -f infra/docker-compose.yml up

down:
	docker compose -f infra/docker-compose.yml down

test:
	cd backend && uv run pytest

seed:
	cd backend && uv run --env-file ../.env python -m app.seed

eval:
	cd backend && uv run --env-file ../.env python -m app.eval.runner

# Generate REAL learning episodes by driving the planner graph in DEMO_MODE
# (deterministic, offline). Populates /learning and /eval outcomes from genuine
# runs and recorded human decisions, not fixtures.
gen-runs:
	cd backend && uv run --env-file ../.env python -m app.gen_runs --n 12

migrate:
	docker compose -f infra/docker-compose.yml exec api uv run alembic upgrade head

fmt:
	cd backend && uv run ruff format app
