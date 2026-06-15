.PHONY: up down build logs migrate seed run pipeline test fmt lint sh psql

up:
	docker compose up -d

build:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.seeds.sources

pipeline:
	docker compose exec api python -m app.pipeline.daily

run:
	docker compose exec api uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q

fmt:
	ruff format app tests

lint:
	ruff check app tests

sh:
	docker compose exec api bash

psql:
	docker compose exec db psql -U ai -d ai_news
