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
- `pyproject.toml` declares Python dependencies.
- `uv.lock` is the committed Python dependency lockfile.

## Development Commands

Show available shortcuts:

```bash
make help
```

Build the test image:

```bash
make build-test
```

Check the dependency lockfile:

```bash
make lock-check
```

Regenerate `uv.lock` after changing Python dependencies:

```bash
make lock
```

Run lint and format checks:

```bash
make lint
make format-check
```

Apply formatting:

```bash
make format
```

Run the fast test suite:

```bash
make test
```

Run the full test suite, including PostgreSQL integration tests:

```bash
make test-db
```

Run py_compile:

```bash
make py-compile
```

Check whitespace:

```bash
make diff-check
```

Run full Docker-first verification:

```bash
make verify
```

## Database Operations

Start PostgreSQL:

```bash
make up-db
```

Apply migrations:

```bash
make migrate
```

Check database connectivity:

```bash
make check-db
```

Generate a Fernet encryption key:

```bash
make generate-key
```

Run retention cleanup:

```bash
make cleanup-dry-run
make cleanup
```

## Running Services

Start the production-like services:

```bash
make up-db
make up
```

View service state:

```bash
make ps
make logs
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
- `references/commands.md`: Telegram command reference and signal syntax.
- `references/trading_flow.md`: order flow, pending orders, validation, and schema summary.
- `references/deployment_runbook.md`: DigitalOcean VPS deployment runbook.
- `references/backup_restore_runbook.md`: PostgreSQL backup restore verification.
- `references/production_readiness.md`: production readiness implementation record.
- `references/deployment_engineering.md`: engineering rollout record for lint, CI, Dependabot, and deployment.
