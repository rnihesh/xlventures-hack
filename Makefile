.PHONY: dev demo down install api test seed eval migrate fmt

install:
	cd backend && uv sync --extra dev

# Run the API with whatever is configured in ./.env (real OpenAI key if set,
# otherwise deterministic offline mode).
api:
	cd backend && uv run --env-file ../.env uvicorn app.main:app --reload --port 8000

# Run the API forced into deterministic DEMO_MODE (reproducible, offline).
demo:
	@echo "Booting Intelligent NBA backend in DEMO_MODE (deterministic, offline, no API keys)..."
	@echo ""
	@echo "  API:       http://localhost:8000"
	@echo "  Docs:      http://localhost:8000/docs  (interactive OpenAPI)"
	@echo "  Health:    http://localhost:8000/health"
	@echo "  Requests:  scripts/requests.http  (curl / REST-client examples for every endpoint)"
	@echo ""
	@echo "  Frontend:  in another terminal run 'cd frontend && npm install && npm run dev' (http://localhost:3000)"
	@echo ""
	cd backend && DEMO_MODE=1 uv run --env-file ../.env uvicorn app.main:app --port 8000

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

migrate:
	docker compose -f infra/docker-compose.yml exec api uv run alembic upgrade head

fmt:
	cd backend && uv run ruff format app
