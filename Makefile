.PHONY: help up down db-migrate db-seed db-status db-reset test test-live lint format api workers dashboard

help:
	@echo "Comandos disponibles:"
	@echo "  make up           Levanta postgres, redis, minio"
	@echo "  make down         Para los servicios"
	@echo "  make db-migrate   Aplica todas las migraciones de db/migrations/"
	@echo "  make db-seed      Carga seeds (entidades Aragón, blacklist)"
	@echo "  make db-status    Lista migraciones aplicadas"
	@echo "  make db-reset     Borra y recrea la BD (¡destructivo!)"
	@echo "  make test         Tests no-live (rápidos, sin LLMs reales)"
	@echo "  make test-live    Tests con LLM real (cuesta dinero)"
	@echo "  make lint         ruff + mypy"
	@echo "  make format       ruff format"
	@echo "  make api          Levanta API local"
	@echo "  make workers      Levanta workers local"

up:
	docker compose up -d postgres redis minio

down:
	docker compose down

db-migrate:
	@for f in db/migrations/*.sql; do \
		echo ">> aplicando $$f"; \
		docker compose exec -T postgres psql -U redactia -d redactia -v ON_ERROR_STOP=1 -f - < $$f; \
	done

db-seed:
	@echo ">> seed entidades Aragón"
	@docker compose exec -T postgres psql -U redactia -d redactia -v ON_ERROR_STOP=1 -f - < db/seeds/entidades_aragon.sql
	@echo ">> seed blacklist dominios"
	@python scripts/load_blacklist.py

db-status:
	docker compose exec postgres psql -U redactia -d redactia -c "\dt"

db-reset:
	docker compose exec postgres psql -U redactia -d postgres -c "DROP DATABASE IF EXISTS redactia;"
	docker compose exec postgres psql -U redactia -d postgres -c "CREATE DATABASE redactia;"
	$(MAKE) db-migrate

test:
	cd api && uv run pytest -m "not live"
	cd workers && uv run pytest -m "not live"

test-live:
	cd api && uv run pytest -m live
	cd workers && uv run pytest -m live

lint:
	cd api && uv run ruff check src tests && uv run mypy src
	cd workers && uv run ruff check src tests && uv run mypy src

format:
	cd api && uv run ruff format src tests
	cd workers && uv run ruff format src tests

api:
	cd api && uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

workers:
	cd workers && uv run python -m src.main

dashboard:
	cd dashboard && pnpm dev
