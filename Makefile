SHELL := /bin/sh

COMPOSE ?= docker compose
UV_IMAGE ?= ghcr.io/astral-sh/uv:python3.11-bookworm-slim
LOG_SERVICE ?= bot
LOG_TAIL ?= 80
PY_COMPILE_FILES := app/*.py app/repositories/*.py alembic/env.py alembic/versions/*.py tests/*.py

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; print "Usage: make <target>"; print ""; print "Targets:"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: build
build: ## Build production Docker images
	$(COMPOSE) build

.PHONY: build-test
build-test: ## Build the Docker test image
	$(COMPOSE) build test

.PHONY: up-db
up-db: ## Start PostgreSQL
	$(COMPOSE) up -d postgres

.PHONY: migrate
migrate: ## Apply Alembic migrations
	$(COMPOSE) run --rm bot alembic upgrade head

.PHONY: check-db
check-db: ## Check database connectivity
	$(COMPOSE) run --rm bot python -m app.main --check-db

.PHONY: up
up: ## Start production-like long-running services
	$(COMPOSE) up -d bot maintenance db-backup

.PHONY: deploy
deploy: ## Build, migrate, check DB, and start services
	$(MAKE) build
	$(MAKE) up-db
	$(MAKE) migrate
	$(MAKE) check-db
	$(MAKE) up

.PHONY: down
down: ## Stop and remove Docker Compose services
	$(COMPOSE) down

.PHONY: ps
ps: ## Show Docker Compose service state
	$(COMPOSE) ps

.PHONY: logs
logs: ## Show recent service logs, override with LOG_SERVICE=name LOG_TAIL=80
	$(COMPOSE) logs --tail $(LOG_TAIL) $(LOG_SERVICE)

.PHONY: generate-key
generate-key: ## Generate a Fernet encryption key
	$(COMPOSE) run --rm bot python -m app.main --generate-key

.PHONY: cleanup-dry-run
cleanup-dry-run: ## Preview retention cleanup
	$(COMPOSE) run --rm bot python -m app.main --cleanup-retention --dry-run

.PHONY: cleanup
cleanup: ## Run retention cleanup
	$(COMPOSE) run --rm bot python -m app.main --cleanup-retention

.PHONY: lock
lock: ## Regenerate uv.lock with Dockerized uv
	docker run --rm -v "$$PWD:/app" -w /app $(UV_IMAGE) uv lock

.PHONY: lock-check
lock-check: ## Check that uv.lock is in sync
	$(COMPOSE) run --rm test uv lock --check

.PHONY: lint
lint: ## Run Ruff lint
	$(COMPOSE) run --rm test ruff check .

.PHONY: format-check
format-check: ## Check Ruff formatting
	$(COMPOSE) run --rm test ruff format --check .

.PHONY: format
format: ## Apply Ruff lint fixes and formatting
	$(COMPOSE) run --rm test ruff check --fix .
	$(COMPOSE) run --rm test ruff format .

.PHONY: test
test: ## Run fast pytest suite
	$(COMPOSE) run --rm test python -m pytest

.PHONY: test-db
test-db: ## Run full pytest suite with PostgreSQL integration tests
	$(MAKE) up-db
	$(COMPOSE) run --rm test python -m pytest --run-db

.PHONY: py-compile
py-compile: ## Compile Python files
	$(COMPOSE) run --rm test python -m py_compile $(PY_COMPILE_FILES)

.PHONY: diff-check
diff-check: ## Check git whitespace errors
	git diff --check

.PHONY: verify
verify: ## Run the full Docker-first verification suite
	$(MAKE) build-test
	$(MAKE) lock-check
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) test-db
	$(MAKE) py-compile
	$(MAKE) diff-check
