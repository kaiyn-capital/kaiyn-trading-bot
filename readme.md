# Kaiyn Trading Bot

[![CI](https://github.com/kaiyn-capital/kaiyn-trading-bot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kaiyn-capital/kaiyn-trading-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![uv](https://img.shields.io/badge/dependencies-uv-261230?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![Docker Compose](https://img.shields.io/badge/Docker%20Compose-runtime-2496ED?logo=docker&logoColor=white)](./compose.yml)
[![CD: GHCR + SSH](https://img.shields.io/badge/CD-GHCR%20%2B%20SSH-24292F?logo=githubactions&logoColor=white)](.github/workflows/release.yml)

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](./pyproject.toml)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](./compose.yml)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-22.7-26A5E4?logo=telegram&logoColor=white)](https://python-telegram-bot.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0.49-D71F00)](https://www.sqlalchemy.org/)
[![Alembic](https://img.shields.io/badge/Alembic-1.18.4-6BA81E)](https://alembic.sqlalchemy.org/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-261230?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![pytest](https://img.shields.io/badge/tests-pytest%209.0.3-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Dependabot](https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white)](./.github/dependabot.yml)

> 🌐 [中文版 README](readme_zh.md)

Kaiyn Trading Bot is a Telegram-integrated trading signal execution bot for Bitget USDT-FUTURES. The project is designed to production-ready standards, covering order confirmation flows, exchange rule validation, encrypted credential storage, audit trails, backup and restore, and CI/CD.

Users can configure encrypted API credentials via Telegram, set a fixed 1R risk amount, and submit market or GTC limit orders from trading signal buttons.

> **Risk Disclaimer:** This project connects to live exchange APIs and submits real futures orders. Bitget API keys should be granted trading permissions only — do not grant withdrawal permissions.

## Highlights

- PostgreSQL-backed pending orders with row locking to prevent duplicate submissions from repeated clicks.
- Deterministic Bitget `clientOid` generation and stale `processing` reconciliation via official Bitget order lookup, without automatic resubmission.
- Decimal-based order sizing on the critical path, persisted with PostgreSQL `Numeric(38, 18)` fields for prices, quantities, notional value, risk, and fees.
- Hard local risk caps for maximum position value and per-user daily trade count, with global defaults and optional user-level stricter overrides.
- Bitget contract-rule validation before execution — checks symbol status, minimum order size, notional value, precision, and per-order limits before submitting.
- Market / GTC limit order flow with fixed 1R sizing, supporting both market orders and limit order confirmation flows.
- Encrypted API credential storage using Fernet encryption for Bitget API Key, Secret Key, and Passphrase.
- PostgreSQL-backed Telegram preview sessions and tokenized callback flows, so pending previews survive Bot restarts within their TTL.
- Admin alerts, health checks, and audit trail via `/admin_health`, `/admin_audit`, startup notifications, and exception alerts.
- Docker-first deployment with retention and backup, including log rotation, DB retention cleanup, local PostgreSQL dumps, and optional encrypted Cloudflare R2 offsite backups.
- CI/CD with Ruff, mypy, Alembic checks, pytest, PostgreSQL integration tests, GHCR image publishing, VPS SSH deployment, and Dependabot.

## Architecture

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"transparent","primaryColor":"#111827","primaryBorderColor":"#38bdf8","primaryTextColor":"#f8fafc","secondaryColor":"#1f2937","secondaryBorderColor":"#64748b","secondaryTextColor":"#f8fafc","tertiaryColor":"#0f172a","tertiaryBorderColor":"#475569","tertiaryTextColor":"#f8fafc","lineColor":"#475569","fontFamily":"Inter, ui-sans-serif, system-ui, sans-serif"}}}%%
flowchart TD
    users["Telegram users"] --> bot["bot service<br/>python-telegram-bot"]
    admins["Admins / traders"] --> bot

    bot --> db["PostgreSQL<br/>users, trades, pending_orders, audit logs"]
    bot --> bitget["Bitget USDT-FUTURES API"]
    bot --> channels["Telegram channels / groups / forum topics"]

    maintenance["maintenance service<br/>30-day retention cleanup"] --> db
    backup["db-backup service<br/>gzip SQL dump + checksum"] --> db
    backup --> files["backups/"]
    backup --> r2["Cloudflare R2<br/>encrypted offsite latest backup"]

    ci["GitHub Actions CI"] --> test["test service<br/>Ruff + mypy + pytest + DB integration"]
    test --> db
    ci --> ghcr["GHCR<br/>multi-arch release image"]
    ghcr --> deploy["VPS SSH CD<br/>deploy image digest"]
    deploy --> bot

    classDef actor fill:#111827,stroke:#38bdf8,color:#f8fafc;
    classDef runtime fill:#0f172a,stroke:#60a5fa,color:#f8fafc;
    classDef storage fill:#111827,stroke:#94a3b8,color:#f8fafc;
    classDef external fill:#1f2937,stroke:#64748b,color:#f8fafc;
    classDef ops fill:#172033,stroke:#38bdf8,color:#f8fafc;

    class users,admins actor;
    class bot,maintenance,backup,test ops;
    class db,files storage;
    class bitget,channels,ci,ghcr,r2 external;
    class deploy ops;
```

## Demo Flow

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"transparent","primaryColor":"#111827","primaryBorderColor":"#38bdf8","primaryTextColor":"#f8fafc","secondaryColor":"#1f2937","secondaryBorderColor":"#64748b","secondaryTextColor":"#f8fafc","tertiaryColor":"#0f172a","tertiaryBorderColor":"#475569","tertiaryTextColor":"#f8fafc","lineColor":"#475569","fontFamily":"Inter, ui-sans-serif, system-ui, sans-serif","actorBkg":"#e2e8f0","actorBorder":"#38bdf8","actorTextColor":"#0f172a","actorLineColor":"#475569","signalColor":"#64748b","signalTextColor":"#111827","labelBoxBkgColor":"#111827","labelBoxBorderColor":"#38bdf8","labelTextColor":"#f8fafc","activationBkgColor":"#172033","activationBorderColor":"#60a5fa","noteBkgColor":"#1f2937","noteTextColor":"#f8fafc"}}}%%
sequenceDiagram
    actor Trader as Trader / Admin
    actor User as Telegram User
    participant Bot as Telegram Bot
    participant DB as PostgreSQL
    participant Rules as Bitget Contract Rules
    participant Bitget as Bitget Order API
    participant Channel as Channel / Topic

    Trader->>Bot: /send_signal
    Bot->>Channel: Forward signal with market / limit actions
    User->>Bot: Select market or GTC limit order
    Bot->>Rules: Fetch price and contract constraints
    Rules-->>Bot: Symbol status, precision, min/max rules
    Bot->>DB: Create pending_order
    Bot-->>User: Show confirmation preview
    User->>Bot: Confirm order
    Bot->>DB: Claim pending_order with row lock
    Bot->>Rules: Revalidate before execution
    Bot->>Bitget: Submit market or GTC limit order
    Bitget-->>Bot: Order result or classified error
    Bot->>DB: Persist trade result and audit event
    Bot-->>User: Return execution summary
```

![Trading signal execution flow](docs/assets/screenshots/trading-flow-showcase.png)

![Operational readiness screenshots](docs/assets/screenshots/operations-showcase.png)

## Tech Stack

| Area | Choice |
| --- | --- |
| Runtime | Python 3.11 |
| Bot framework | `python-telegram-bot` 22.7 |
| Exchange integration | Bitget USDT-FUTURES REST API via `httpx` 0.28.1 |
| Database | PostgreSQL 16 + SQLAlchemy asyncio 2.0.49 + `asyncpg` 0.31.0 |
| Schema migration | Alembic 1.18.4 |
| Credential security | `cryptography` Fernet 48.0.0 |
| Financial values | `Decimal` critical path + PostgreSQL `Numeric(38, 18)` |
| Deployment | Docker Compose services: `postgres`, `bot`, `maintenance`, `db-backup` |
| Dependency lock | uv lockfile + `uv sync --locked` |
| Long-term operations | Docker/file log rotation, DB retention, local SQL backup, encrypted R2 offsite backup |
| Testing | pytest 9.0.3 + pytest-asyncio 1.3.0 + PostgreSQL integration tests + 70% critical-path coverage threshold |
| Lint / format | Ruff 0.15.14 |
| Type checking | mypy 2.1.0 on critical path modules |
| CI | GitHub Actions with Docker Compose-first checks |
| CD | GHCR multi-arch image + VPS SSH deployment by digest |
| Dependency automation | Dependabot weekly updates; GitHub Actions patch/minor auto-merge |

## Core Capabilities

- Telegram-based Bitget USDT-FUTURES signal execution.
- Encrypted user API credential storage and API connectivity checks.
- Fixed 1R risk sizing with market and GTC limit order modes, hard position caps, and daily trade limits.
- Persistent pending order, signal, and Telegram preview/session flows backed by PostgreSQL.
- Deterministic `clientOid` generation and stale `processing` reconciliation against Bitget order detail/history.
- Managed channel/group forwarding with Telegram forum topic support.
- Admin health checks, alerts, audit events, retention cleanup, local backups, and encrypted R2 offsite backup/restore.
- Docker Compose local/deployment parity with CI-backed verification.

## Engineering Notes

- Trading state and Telegram conversation sessions are persisted in PostgreSQL, so pending confirmations and active previews survive Bot restarts within their TTL.
- Telegram callback payloads carry short tokens; order/signal/session state lives in PostgreSQL instead of callback data.
- Exchange execution is validated against Bitget contract rules before confirmation and again before order submission.
- Order sizing and risk comparison use Decimal values through the critical path, with explicit JSON/text conversion at boundaries.
- Telegram output uses HTML formatting helpers that escape dynamic text by default.
- Operations are part of the product surface: health checks, audit events, retention cleanup, backups, and restore documentation are included.
- CI mirrors the Docker Compose runtime path, including lockfile, migration/model, type, and PostgreSQL integration checks instead of relying on host-local services.
- CD publishes multi-arch images to GHCR and deploys production through SSH after environment approval.

## Quick Start

Create `.env`:

```bash
cp .env.template .env
```

Generate a Fernet encryption key and set it as `ENCRYPTION_KEY` in `.env`:

```bash
make build
make generate-key
```

Start PostgreSQL, apply migrations, and launch the Bot:

```bash
make deploy
```

Equivalent Docker Compose commands:

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot python -m app.main --check-db
docker compose up -d bot maintenance db-backup
```

For the full DigitalOcean deployment procedure, see [deployment_runbook.md](references/deployment_runbook.md). For the optional Coolify deployment variant, see [coolify_runbook.md](references/coolify_runbook.md).

## Configuration

Production configuration is injected via `.env`. See [.env.template](.env.template) for a reference of all variables.

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot token |
| `TELEGRAM_ADMIN_IDS` | Comma-separated list of admin Telegram IDs |
| `ENCRYPTION_KEY` | Fernet key for encrypting Bitget API credentials |
| `DATABASE_URL` | PostgreSQL async connection URL |
| `BITGET_API_URL` | Bitget API base URL |
| `SIGNAL_CHART_*` | Optional `/send_signal` chart generation toggle, granularity, candle limit, and timeout |
| `RETENTION_DAYS` | Number of days to retain accumulated records and backups |
| `BACKUP_LOCAL_KEEP_COUNT` | Number of latest local SQL backups to keep |
| `R2_*` / `BACKUP_ENCRYPTION_KEY` | Optional Cloudflare R2 encrypted offsite backup settings |
| `ADMIN_ALERT_*` / `BITGET_ALERT_*` | Admin alert and Bitget consecutive error thresholds |

## Testing & CI

Docker-first verification:

```bash
make verify
```

Equivalent Docker Compose commands:

```bash
docker compose build test
docker compose run --rm test uv lock --check
docker compose up -d postgres
docker compose run --rm test alembic upgrade head
docker compose run --rm test alembic check
docker compose run --rm test ruff check .
docker compose run --rm test ruff format --check .
docker compose run --rm test mypy app/order_flow.py app/order_validation.py app/risk_limits.py app/bitget_errors.py app/config.py --no-error-summary
docker compose run --rm test python -m pytest --run-db
docker compose run --rm test python -m py_compile app/*.py app/repositories/*.py alembic/env.py alembic/versions/*.py scripts/*.py tests/*.py
git diff --check
```

GitHub Actions runs the same Docker Compose flow for lockfile consistency, Alembic migration/model checks, Ruff, mypy, PostgreSQL integration tests with coverage output, `py_compile`, and whitespace checks. After CI passes, the release workflow publishes a multi-arch image to GHCR and deploys it to the VPS via SSH after `production` environment approval. Coolify documentation is retained as an optional deployment variant.

Dependabot checks Python packages and GitHub Actions weekly. GitHub Actions patch/minor PRs can be auto-squash-merged after CI and branch protection pass. Python dependency PRs require manual review.

To update the Python dependency lockfile using Dockerized uv:

```bash
docker run --rm -v "$PWD:/app" -w /app ghcr.io/astral-sh/uv:python3.11-bookworm-slim uv lock
```

## Operations

- The `maintenance` service runs daily cleanup of records older than 30 days.
- The `db-backup` service produces gzip SQL backups with checksum and manifest files on `BACKUP_INTERVAL_SECONDS` intervals.
- Run `make backup-now` before risky operations and `make restore-latest` to restore the latest local backup.
- When Cloudflare R2 is configured, `db-backup` uploads encrypted backups offsite and `make disaster-restore` downloads the latest R2 backup before restoring it.
- Both Docker container logs and Bot file logs are configured with rotation.
- `/admin_health` reports DB, backup, cleanup, Bitget API, and recent error status.
- `/admin_audit [limit]` displays a summary of admin, signal sender, and order execution events.

For backup restore verification, see [backup_restore_runbook.md](references/backup_restore_runbook.md).

## Documentation

| Document | Description |
| --- | --- |
| [commands.md](references/commands.md) | Telegram command reference, signal syntax, topic forwarding, smoke tests |
| [trading_flow.md](references/trading_flow.md) | Order flow, pending orders, exchange-rule validation, error categories, schema summary |
| [deployment_runbook.md](references/deployment_runbook.md) | DigitalOcean VPS deployment, update, rollback, troubleshooting |
| [coolify_runbook.md](references/coolify_runbook.md) | Optional Coolify deployment variant with GHCR image pipeline |
| [backup_restore_runbook.md](references/backup_restore_runbook.md) | PostgreSQL backup restore verification |
| [production_readiness.md](references/production_readiness.md) | Production readiness design record |
| [deployment_engineering.md](references/deployment_engineering.md) | CI, Dependabot, lint/format, deployment engineering baseline |

## Project Structure

```text
.
├── app/                    # Telegram bot, Bitget client, order flow, repositories
├── alembic/                # Alembic migration environment and versions
├── tests/                  # pytest unit and PostgreSQL integration tests
├── scripts/                # backup, R2 upload/download, and restore helper scripts
├── docs/                   # GitHub Pages site (index.html, CNAME, assets)
├── references/             # command, trading, deployment, backup, readiness documentation
├── compose.yml             # postgres, bot, test, maintenance, db-backup services
├── compose.prod.yml        # image-based production override for GHCR deployments
├── compose.coolify.yml     # optional Coolify Docker Compose application
├── Dockerfile
├── Makefile
├── pyproject.toml
├── uv.lock
└── .env.template
```

## Security Notes

- `.env`, database data, logs, and backups are not committed to Git.
- Runtime logs use a summarization strategy and do not output API keys, secrets, passphrases, or full exchange responses.
- PostgreSQL backups contain encrypted API credentials and trade records — treat them as sensitive data.
- If `ENCRYPTION_KEY` is lost, existing encrypted API credentials cannot be decrypted.
- If `BACKUP_ENCRYPTION_KEY` is lost, encrypted Cloudflare R2 backups cannot be decrypted.
- Telegram channel/group forwarding requires the Bot to have the appropriate admin permissions.
