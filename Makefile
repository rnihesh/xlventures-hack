.PHONY: dev demo down install test seed eval migrate fmt

install:
	cd backend && uv sync --extra dev

demo:
	@echo "Booting Intelligent NBA backend in DEMO_MODE (deterministic, offline, no API keys)..."
	@echo ""
	@echo "  API:       http://localhost:8000"
	@echo "  Docs:      http://localhost:8000/docs  (interactive OpenAPI)"
	@echo "  Health:    http://localhost:8000/health"
	@echo "  Requests:  scripts/requests.http  (curl / REST-client examples for every endpoint)"
	@echo ""
	@echo "  Frontend:  in another terminal run 'cd frontend && npm install && npm run dev' (http://localhost:3000)"
	@echo "             set NEXT_PUBLIC_API_URL=http://localhost:8000 so the UI reaches this API."
	@echo ""
	cd backend && DEMO_MODE=1 uv run uvicorn app.main:app --port 8000

dev:
	docker compose -f infra/docker-compose.yml up

down:
	docker compose -f infra/docker-compose.yml down

test:
	cd backend && uv run pytest

seed:
	cd backend && uv run python -m app.seed

eval:
	cd backend && uv run python -m app.eval.runner

migrate:
	docker compose -f infra/docker-compose.yml exec api uv run alembic upgrade head

fmt:
	cd backend && uv run ruff format app
