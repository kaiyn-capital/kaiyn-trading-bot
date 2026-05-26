SHELL := /bin/sh

COMPOSE ?= docker compose
COMPOSE_PROD ?= $(COMPOSE) -f compose.yml -f compose.prod.yml
UV_IMAGE ?= ghcr.io/astral-sh/uv:python3.11-bookworm-slim
LOG_SERVICE ?= bot
LOG_TAIL ?= 80
BOT_IMAGE_FILE ?= .bot_image
RESOLVED_BOT_IMAGE := $(strip $(if $(BOT_IMAGE),$(BOT_IMAGE),$(shell [ -f "$(BOT_IMAGE_FILE)" ] && sed -n '1p' "$(BOT_IMAGE_FILE)")))
BACKUP_COMPOSE := $(if $(RESOLVED_BOT_IMAGE),$(COMPOSE_PROD),$(COMPOSE))
BACKUP_BOT_IMAGE_ENV := $(if $(RESOLVED_BOT_IMAGE),BOT_IMAGE="$(RESOLVED_BOT_IMAGE)",)
PY_COMPILE_FILES := app/*.py app/repositories/*.py alembic/env.py alembic/versions/*.py scripts/*.py tests/*.py

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

.PHONY: require-bot-image
require-bot-image:
	@if [ -z "$(BOT_IMAGE)" ]; then \
		echo "BOT_IMAGE is required. Example: BOT_IMAGE=ghcr.io/kaiyn-capital/kaiyn-trading-bot@sha256:<digest> make deploy-image"; \
		exit 1; \
	fi

.PHONY: pull-image
pull-image: require-bot-image ## Pull bot and maintenance images from BOT_IMAGE
	BOT_IMAGE="$(BOT_IMAGE)" $(COMPOSE_PROD) pull bot maintenance db-backup

.PHONY: migrate-image
migrate-image: require-bot-image ## Apply migrations using BOT_IMAGE
	BOT_IMAGE="$(BOT_IMAGE)" $(COMPOSE_PROD) run --rm bot alembic upgrade head

.PHONY: check-db-image
check-db-image: require-bot-image ## Check database connectivity using BOT_IMAGE
	BOT_IMAGE="$(BOT_IMAGE)" $(COMPOSE_PROD) run --rm bot python -m app.main --check-db

.PHONY: up-image
up-image: require-bot-image ## Start long-running services using BOT_IMAGE
	BOT_IMAGE="$(BOT_IMAGE)" $(COMPOSE_PROD) up -d bot maintenance db-backup
	printf '%s\n' "$(BOT_IMAGE)" > "$(BOT_IMAGE_FILE)"

.PHONY: deploy-image
deploy-image: require-bot-image ## Pull BOT_IMAGE, migrate, check DB, and start services
	$(MAKE) up-db
	$(MAKE) pull-image BOT_IMAGE="$(BOT_IMAGE)"
	$(MAKE) migrate-image BOT_IMAGE="$(BOT_IMAGE)"
	$(MAKE) check-db-image BOT_IMAGE="$(BOT_IMAGE)"
	$(MAKE) up-image BOT_IMAGE="$(BOT_IMAGE)"

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

.PHONY: backup-now
backup-now: ## Run a PostgreSQL backup immediately
	$(BACKUP_BOT_IMAGE_ENV) $(BACKUP_COMPOSE) run --rm db-backup sh /scripts/backup_database.sh

.PHONY: r2-download-latest
r2-download-latest: ## Download and decrypt the latest R2 backup into ./backups
	$(BACKUP_BOT_IMAGE_ENV) $(BACKUP_COMPOSE) run --rm db-backup python /scripts/r2_backup.py download-latest --output-dir /backups --status-output /backups/r2_restore_status.json --filename-output /backups/r2_latest_backup_filename.txt

.PHONY: restore-latest
restore-latest: ## Restore the latest local PostgreSQL backup
	$(BACKUP_BOT_IMAGE_ENV) COMPOSE="$(BACKUP_COMPOSE)" sh scripts/restore_latest_backup.sh

.PHONY: disaster-restore
disaster-restore: ## Download latest R2 backup and restore it
	$(BACKUP_BOT_IMAGE_ENV) COMPOSE="$(BACKUP_COMPOSE)" sh scripts/disaster_restore_from_r2.sh

.PHONY: generate-backup-key
generate-backup-key: ## Generate a Fernet key for BACKUP_ENCRYPTION_KEY
	$(BACKUP_BOT_IMAGE_ENV) $(BACKUP_COMPOSE) run --rm bot python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

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

.PHONY: mypy
mypy: ## Run mypy type checking on critical path modules
	$(COMPOSE) run --rm test mypy app/order_flow.py app/order_validation.py app/risk_limits.py app/bitget_errors.py app/config.py --no-error-summary

.PHONY: migrate-test
migrate-test: ## Run Alembic upgrade head on test database
	$(MAKE) up-db
	$(COMPOSE) run --rm test alembic upgrade head

.PHONY: alembic-check
alembic-check: ## Check Alembic migration-model consistency
	$(COMPOSE) run --rm test alembic check

.PHONY: test
test: ## Run fast pytest suite
	$(COMPOSE) run --rm test python -m pytest

.PHONY: test-db
test-db: ## Run full pytest suite with PostgreSQL integration tests
	$(MAKE) up-db
	$(COMPOSE) run --rm test python -m pytest --run-db

.PHONY: coverage
coverage: ## Run pytest with coverage on critical path modules (70% threshold)
	$(COMPOSE) run --rm test python -m pytest --cov --cov-report=term-missing --cov-fail-under=70

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
	$(MAKE) migrate-test
	$(MAKE) alembic-check
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) mypy
	$(MAKE) test-db
	$(MAKE) py-compile
	$(MAKE) diff-check
