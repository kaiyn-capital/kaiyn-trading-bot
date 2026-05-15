# AGENTS.md

This file provides repository-specific guidance for coding agents working on Kaiyn Trading Bot.

## Project Overview

Kaiyn Trading Bot is a Telegram bot for Bitget USDT-FUTURES signal execution. It lets users store encrypted Bitget API credentials, set a fixed 1R risk amount, receive trading signals, and submit market or GTC limit orders from Telegram. Admin users can manage traders, forwarding channels, Telegram forum topics, health checks, alerts, audits, retention, and backups.

## Current Architecture

- Runtime is Docker Compose first.
- Python runtime is fixed to Python 3.11.
- PostgreSQL is the only supported database.
- SQLAlchemy is used with async engine/session.
- Alembic owns schema creation and migrations.
- `pyproject.toml` is the only Python dependency source.

## Development Commands

Build the test image:

```bash
docker compose build test
```

Run lint and format checks:

```bash
docker compose run --rm test ruff check .
docker compose run --rm test ruff format --check .
```

Apply formatting:

```bash
docker compose run --rm test ruff check --fix .
docker compose run --rm test ruff format .
```

Run the fast test suite:

```bash
docker compose run --rm test python -m pytest
```

Run the full test suite, including PostgreSQL integration tests:

```bash
docker compose up -d postgres
docker compose run --rm test python -m pytest --run-db
```

Run py_compile:

```bash
docker compose run --rm test python -m py_compile app/*.py app/repositories/*.py alembic/env.py alembic/versions/*.py tests/*.py
```

Check whitespace:

```bash
git diff --check
```

## Database Operations

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Apply migrations:

```bash
docker compose run --rm bot alembic upgrade head
```

Check database connectivity:

```bash
docker compose run --rm bot python -m app.main --check-db
```

Generate a Fernet encryption key:

```bash
docker compose run --rm bot python -m app.main --generate-key
```

Run retention cleanup:

```bash
docker compose run --rm bot python -m app.main --cleanup-retention --dry-run
docker compose run --rm bot python -m app.main --cleanup-retention
```

## Running Services

Start the production-like services:

```bash
docker compose up -d postgres
docker compose up -d bot maintenance db-backup
```

View service state:

```bash
docker compose ps
docker compose logs --tail 80 bot
```

The `test` service is only for checks and should not be kept running in production.

## Key Modules

- `app/bot.py`: Telegram bot entrypoint, lifecycle, handler registration, callback router, shared helpers.
- `app/bot_account_handlers.py`: `/start`, `/help`, `/status`, `/balance`, `/setapi`, `/settings`, 1R setup.
- `app/bot_admin_*.py`: admin, user, channel, topic, messaging, health, and audit handlers.
- `app/bot_order_handlers.py`: `/send_signal`, order mode callbacks, pending order confirm/cancel, order execution.
- `app/order_flow.py`: signal parsing, order preview, Bitget contract-rule validation, order execution helpers.
- `app/bitget_api.py`: low-level Bitget API client and higher-level trade manager.
- `app/bitget_errors.py`: Bitget/API error classification and user-facing message mapping.
- `app/database.py`: async DB manager and repository getter facade.
- `app/repositories/`: repository implementations.
- `app/models.py`: SQLAlchemy models.
- `app/audit.py`: structured audit helpers.
- `app/health.py`: admin health report helpers.
- `alembic/versions/`: schema migrations.
- `tests/`: pytest unit and opt-in PostgreSQL integration tests.

## Repository Hygiene

- Do not commit `.env`, logs, backups, database files, cache directories, or generated package metadata.
- Runtime logs are summarized, but still treat them as internal operational data.
- Backups contain encrypted user API credentials and trading records; treat them as sensitive.
- Keep public documentation generic where possible. Avoid committing local backup filenames, real Telegram IDs, real API keys, VPS IPs, or production-specific secrets.

## Documentation

- `readme.md`: public project overview and main setup instructions.
- `docs/commands.md`: Telegram command reference and signal syntax.
- `docs/trading_flow.md`: order flow, pending orders, validation, and schema summary.
- `docs/deployment_runbook.md`: DigitalOcean VPS deployment runbook.
- `docs/backup_restore_runbook.md`: PostgreSQL backup restore verification.
- `docs/production_readiness.md`: production readiness implementation record.
- `docs/deployment_engineering.md`: engineering rollout record for lint, CI, Dependabot, and deployment.
