.PHONY: dev down seed eval migrate fmt

dev:
	docker compose -f infra/docker-compose.yml up

down:
	docker compose -f infra/docker-compose.yml down

seed:
	@echo "seed: placeholder, wire up data seeding here"

eval:
	@echo "eval: placeholder, wire up evaluation harness here"

migrate:
	docker compose -f infra/docker-compose.yml exec api alembic upgrade head

fmt:
	docker compose -f infra/docker-compose.yml run --rm api ruff format app
