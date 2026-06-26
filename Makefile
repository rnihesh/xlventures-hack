.PHONY: dev down seed eval migrate fmt

dev:
	docker compose -f infra/docker-compose.yml up

down:
	docker compose -f infra/docker-compose.yml down

seed:
	cd backend && python -m app.seed

eval:
	cd backend && python -m app.eval.runner

migrate:
	docker compose -f infra/docker-compose.yml exec api alembic upgrade head

fmt:
	docker compose -f infra/docker-compose.yml run --rm api ruff format app
