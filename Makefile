# Everything Docker for Nafas goes through here, pinned to the native engine:
# Docker Desktop (often the default context) runs in a VM that cannot see the
# GPU, and the dialect-router needs it. Override with DOCKER_CONTEXT=... if needed.
export DOCKER_CONTEXT ?= default

COMPOSE := docker compose

.PHONY: up up-cpu down ps logs build db-roles migrate seed storage test test-web web-dev test-gpu-services gpu-check

up:  ## the whole stack, GPU services on the GPU
	$(COMPOSE) up -d --build

up-cpu:  ## the whole stack on a machine without a GPU (the dialect-router runs on CPU)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.cpu.yml up -d --build

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100

build:
	$(COMPOSE) build

db-roles:  ## create the database roles on a volume made before they existed
	$(COMPOSE) exec -T postgres psql -U nafas -d nafas -v ON_ERROR_STOP=1 < deploy/postgres/roles.sql

migrate:  ## apply database migrations (against the stack's Postgres on :5433)
	uv run alembic upgrade head

seed:  ## create or update the specializations
	uv run python -m nafas_identity.cli seed

storage:  ## create the S3 bucket
	uv run python -m scripts.init_storage

test:  ## the workspace suite, then each GPU service's own suite
	uv run pytest
	$(MAKE) test-web
	$(MAKE) test-gpu-services

test-web:
	cd web && npm test && npm run typecheck

web-dev:  ## the web app with hot reload on :5173, proxying /api to the gateway
	cd web && npm run dev

test-gpu-services:
	cd services/dialect_router && uv run pytest

gpu-check:  ## prove a container can see the GPU
	docker run --rm --device nvidia.com/gpu=all ubuntu:24.04 nvidia-smi -L
