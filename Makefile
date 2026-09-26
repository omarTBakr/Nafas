# Everything Docker for Nafas goes through here, pinned to the native engine:
# Docker Desktop (often the default context) runs in a VM that cannot see the
# GPU, and the dialect-router needs it. Override with DOCKER_CONTEXT=... if needed.
export DOCKER_CONTEXT ?= default
# baked into every image and reported on /health
export GIT_SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null)

COMPOSE := docker compose

.PHONY: up up-cpu down ps logs build db-roles migrate seed storage test test-web web-dev test-gpu-services gpu-check monitoring export-feedback load-test

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
	cd services/stt && uv run pytest
	cd services/tts && uv run pytest
	cd services/embeddings && uv run pytest

monitoring:  ## Prometheus on :9090 and Grafana on :3000 beside the stack
	$(COMPOSE) --profile monitoring up -d prometheus grafana

load-test:  ## 50 simulated patients for a minute against the gateway; fails on a missed SLO
	uv run python -m scripts.load_test --users 50 --seconds 60

export-feedback:  ## de-identified feedback datasets into data/feedback/<date> (needs FEEDBACK_SALT)
	uv run python -m scripts.export_feedback

gpu-check:  ## prove a container can see the GPU
	docker run --rm --device nvidia.com/gpu=all ubuntu:24.04 nvidia-smi -L

# --- checks that need the GPU services or a person (docs/CHECKLIST.md, "Needs you") ---

check-stt:  ## WER per dialect on labelled clips: make check-stt CLIPS=path/to/clips
	uv run python -m scripts.checks.stt_wer $(CLIPS)

check-tts:  ## which dialects the tts model knows, and a sample WAV of each in tts-samples/
	uv run python -m scripts.checks.tts_probe

listening-test:  ## the blind v2/v3 Egyptian page: make listening-test V2_URL=... V3_URL=...
	uv run python -m scripts.checks.listening_test build --v2-url $(V2_URL) --v3-url $(V3_URL)

normaliser-sheet:  ## normaliser-review.csv for native speakers
	uv run python -m scripts.checks.normaliser_sheet

check-dialects:  ## the dialect-router on labelled sentences: make check-dialects SAMPLES=path/to/samples.csv
	uv run python -m scripts.checks.dialect_router $(SAMPLES)
