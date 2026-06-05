# AGENTS.md

Repository-specific guidance for coding agents working on Kaiyn Trading Bot.
Keep this file short and operational. Put long setup, deployment, and feature
documentation in `readme.md` or `references/*.md`.

## Operating Rules

- Use Traditional Chinese for normal user-facing conversation. Use English for
  code comments and commit/PR titles.
- Do not guess unclear requirements. State the ambiguity and ask before making a
  risky product or trading-flow decision.
- Prefer small, directly traceable changes. Do not refactor adjacent code unless
  it is required for the task.
- Never overwrite, discard, or revert user changes unless explicitly requested.
- Treat trading, credential, backup, and database data as sensitive operational
  data.

## Project Context

- Kaiyn Trading Bot is a Telegram bot for Bitget `USDT-FUTURES` signal
  execution.
- Runtime is Docker Compose first.
- Python is fixed to 3.11.
- PostgreSQL is the only supported database.
- SQLAlchemy uses async engine/session.
- Alembic owns schema creation and migrations.
- Python dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

## Code Intelligence

When reviewing, planning, or modifying code, use codegraph before broad
`rg`/file-read exploration when it is available.

- For architecture, feature flow, bug context, or "how does this work" tasks,
  first use `codegraph_context`.
- For symbol lookup, use `codegraph_search`.
- For impact analysis, use `codegraph_impact`.
- For call paths, use `codegraph_trace` when available.
- If codegraph tools are not already loaded, search for them via `tool_search`
  before falling back to `rg`.
- Use `rg` and direct file reads only to verify exact details not covered by
  codegraph, or when codegraph is unavailable.

## High-Risk Areas

Get local-code evidence and be conservative before changing:

- Bitget signing, API request construction, order placement, and reconciliation.
- `client_order_id`, pending-order idempotency, and `processing` recovery.
- Decimal order sizing, exchange precision/step validation, and risk caps.
- Alembic migrations, model/repository contracts, and persisted DTO shapes.
- API credential encryption, logging redaction, and admin/security boundaries.
- Backup, restore, R2 offsite sync, deployment, and CI permissions.

## Verification

- Use `make help` for the complete command list.
- Use `make verify` before PRs when runtime code, tests, dependencies,
  migrations, or operational behavior changed.
- For narrow docs-only changes, at minimum run `git diff --check`; add targeted
  commands when the docs describe commands, config, or deployment behavior.
- Use Docker-first commands from the Makefile instead of inventing local-only
  equivalents.
- Regenerate `uv.lock` with `make lock` after dependency changes, then check it
  with `make lock-check`.

## Git And PR Rules

- Primary remote is `origin`:
  `https://github.com/kaiyn-capital/kaiyn-trading-bot.git`.
- Do not commit directly to `main` for normal feature, fix, refactor, docs, or
  CI work.
- Before editing, check `git status --short --branch`. If local changes are
  unrelated, do not touch them.
- Branch from updated `main` when it is safe to do so.
- Use neutral branch prefixes such as `feature/`, `fix/`, `docs/`,
  `refactor/`, `chore/`, or `ci/`. Do not use AI/tool/vendor names such as
  `codex/`.
- Commits must follow `$commit` and Conventional Commits.
- Pull requests must follow `$pull-request`.
- Ask for explicit user confirmation before creating a PR unless the user has
  explicitly asked to create it without another confirmation.
- After a PR is merged, return to `main`, pull with `git pull --ff-only origin
  main`, and clean up merged branches only when safe.

## Security And Data Hygiene

- Do not commit `.env`, logs, backups, database files, cache directories, or
  generated package metadata.
- Do not commit real Telegram IDs, API keys, VPS IPs, local backup names, or
  production secrets.
- Backups contain encrypted user API credentials and trading records; treat them
  as sensitive even when encrypted.
- Keep public documentation generic unless production-specific details are
  explicitly required and safe to publish.

## Reference Index

- `readme.md`: public overview and main setup path.
- `Makefile`: source of truth for development, test, lint, migration, backup,
  and verification commands.
- `references/commands.md`: Telegram command and signal syntax reference.
- `references/trading_flow.md`: order flow, pending orders, validation, and
  schema behavior.
- `references/deployment_runbook.md`: DigitalOcean VPS deployment.
- `references/coolify_runbook.md`: optional Coolify deployment.
- `references/backup_restore_runbook.md`: PostgreSQL backup and restore.
- `references/production_readiness.md`: production readiness decisions.
- `references/deployment_engineering.md`: CI, lint, Dependabot, and deployment
  engineering notes.
