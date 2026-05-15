# Deployment Engineering Record

更新日期：2026-05-15

本文件記錄 Kaiyn Trading Bot 的工程化部署設計。專案採 Docker Compose 優先流程，並以相同容器環境執行開發檢查、CI、資料庫 migration、正式部署與維護任務。

## Engineering Baseline

專案已採用下列工程化基準：

- Python 3.11 runtime。
- Docker Compose 作為本地測試與正式部署入口。
- Makefile 作為 Docker Compose 指令捷徑，不取代 Docker Compose。
- PostgreSQL、Alembic migration、async SQLAlchemy。
- `pyproject.toml` 作為 Python 依賴宣告來源，`uv.lock` 作為鎖定檔。
- Ruff 作為 Python lint 與 format 工具。
- pytest 作為測試框架，包含純邏輯、handler 與 PostgreSQL integration tests。
- GitHub Actions CI，以 Docker Compose 執行 Ruff、pytest、DB integration、py_compile 與 whitespace 檢查。
- GitHub Actions CD，在 CI 通過後發布 GHCR multi-arch image，並透過 Coolify webhook 部署到 VPS / Oracle runtime。
- Dependabot 每週檢查 Python packages 與 GitHub Actions；GitHub Actions patch/minor PR 可在 CI 與 branch protection 通過後自動 merge。
- DigitalOcean VPS 與 Oracle Cloud ARM deployment runbooks，涵蓋首次部署、更新、備份拉取、還原連結與故障處理。

## Dependency Management

專案使用 uv 鎖定 Python 依賴：

- `pyproject.toml` 宣告 runtime dependencies 與 dev dependency group。
- `uv.lock` 鎖定完整 transitive dependency graph，並提交到 git。
- Docker runtime image 使用 `uv sync --locked --no-dev --no-editable`。
- Docker test image 使用 `uv sync --locked --no-editable`，包含 dev tools。
- VPS 與本機 host 不需要安裝 uv；uv 由 Docker image 提供。

更新 Python 依賴後，重新產生 lockfile：

```bash
docker run --rm -v "$PWD:/app" -w /app ghcr.io/astral-sh/uv:python3.11-bookworm-slim uv lock
```

## Linter And Formatter

專案使用 `ruff` 作為唯一 Python lint + format 工具。

執行指令：

```bash
docker compose run --rm test ruff check .
docker compose run --rm test ruff format --check .
```

手動修正格式：

```bash
docker compose run --rm test ruff check --fix .
docker compose run --rm test ruff format .
```

設定位置：

- `pyproject.toml` 的 `[dependency-groups].dev`
- `pyproject.toml` 的 `[tool.ruff]`
- `pyproject.toml` 的 `[tool.ruff.lint]`

## GitHub Actions CI

CI 檔案：

- `.github/workflows/ci.yml`

觸發條件：

- push 到 `main`
- PR 指向 `main`
- `workflow_dispatch`

CI 執行項目：

```bash
docker compose version
docker compose build test
docker compose up -d postgres
docker compose run --rm test uv lock --check
docker compose run --rm test ruff check .
docker compose run --rm test ruff format --check .
docker compose run --rm test python -m pytest --run-db
docker compose run --rm test python -m py_compile app/*.py app/repositories/*.py alembic/env.py alembic/versions/*.py tests/*.py
git diff --check
docker compose down -v --remove-orphans
```

CI 不使用 production secrets，不連線 Telegram，也不呼叫 Bitget 真實 API。

## GHCR Image Pipeline And Coolify CD

Release workflow：

- `.github/workflows/release.yml`

觸發條件：

- `CI` workflow 在 `main` push 成功後自動觸發。
- `workflow_dispatch` 可手動觸發。

流程：

```text
CI passed
-> build linux/amd64 + linux/arm64 Docker image
-> push ghcr.io/kylekkkk61/kaiyn-trading-bot:sha-<commit>
-> push ghcr.io/kylekkkk61/kaiyn-trading-bot:main
-> update Coolify BOT_IMAGE after production environment approval
-> trigger Coolify deployment webhook
```

Production deployment 使用 Coolify application 與 `compose.coolify.yml`。`bot` 與 `maintenance` 由 GHCR image 啟動；`postgres` 與 `db-backup` 保留 Docker Compose service model。

GitHub `production` environment 需提供：

```text
COOLIFY_TOKEN
COOLIFY_API_BASE_URL
COOLIFY_APPLICATION_UUID
COOLIFY_WEBHOOK
```

建議 `production` environment 設定 required reviewer，讓 production deploy 在 image 發布後等待人工 approval。

SSH + `make deploy-image` 保留為 manual fallback，不再是 release workflow 的 production executor。

## Makefile Shortcuts

Makefile 封裝常用 Docker Compose 命令：

```bash
make help
make verify
make deploy
make test
make test-db
make lint
make format-check
make migrate
make check-db
make up
make logs
make deploy-image
```

- `make verify` 執行完整 Docker-first 檢查。
- `make deploy` 執行 build、PostgreSQL startup、migration、DB check 與服務啟動。
- `make deploy-image` 使用 `BOT_IMAGE=<ghcr image digest>` 執行 image-based production deployment。
- CI 維持直接執行 Docker Compose 命令，避免 CI 行為被 Makefile abstraction 隱藏。

## Dependabot

Dependabot 設定檔：

- `.github/dependabot.yml`

更新範圍：

- Python package ecosystem：`pyproject.toml` 與 `uv.lock`
- GitHub Actions ecosystem：`.github/workflows/*.yml`

PR 規則：

- 每週一台北時間 09:00 檢查。
- 同時最多 5 個 open PR。
- Python package PR 只建立 PR，不自動 merge。
- GitHub Actions patch/minor PR 在 CI 與 branch protection 通過後可自動 squash merge。
- Major updates 一律人工 review。
- 每個 PR 必須通過 GitHub Actions CI。
- Python package 與 major update PR 由維護者人工檢查 changelog 後合併。

Auto-merge workflow：

- `.github/workflows/dependabot-auto-merge.yml`
- 使用 `pull_request_target`，不 checkout 或執行 PR 內容。
- 只處理 `package-ecosystem == github-actions` 且 `update-type` 為 `version-update:semver-patch` 或 `version-update:semver-minor` 的 Dependabot PR。

GitHub repository settings：

- 啟用 Allow auto-merge。
- `main` branch 啟用 required status checks。
- Required check 至少包含 `Docker Compose checks`。
- 不提供 production secrets 給 auto-merge workflow。

## Deployment Baseline

正式部署規格：

- Provider：DigitalOcean Droplet
- OS：Ubuntu 24.04 LTS
- Instance size：依實際使用量選擇；小型 production target 可從 1 vCPU / 2GB RAM 級別開始
- Runtime：Docker Engine + Docker Compose plugin
- Services：`postgres`、`bot`、`maintenance`、`db-backup`
- Test service：`test` 僅用於檢查，不長駐

部署流程：

- 使用 Docker Compose。
- `compose.coolify.yml` 以 `migrate` 一次性服務執行 Alembic migration。
- 同時啟動 `bot`、`maintenance`、`db-backup`。
- Bot 啟動時不自動套用 migration。
- GitHub Actions 可在 CI 通過與 `production` environment approval 後觸發 Coolify deployment。

部署文件：

- [deployment_runbook.md](deployment_runbook.md)
- [oracle_cloud_arm_runbook.md](oracle_cloud_arm_runbook.md)
- [coolify_runbook.md](coolify_runbook.md)
- [backup_restore_runbook.md](backup_restore_runbook.md)

## Security Baseline

正式環境安全規範：

- `.env` 使用正式強密碼，不使用範例值。
- `TELEGRAM_ADMIN_IDS` 僅填入實際管理員。
- Bitget API 授予交易所需最小權限。
- Bitget API 不開提現權限。
- Bitget API 不綁定 IP whitelist。
- VPS firewall 只開 SSH。
- PostgreSQL host port 綁定 `127.0.0.1:5432`。
- 備份檔定期從 VPS 拉到本機或雲端保存。

## Out Of Scope

下列項目不屬於本專案工程化範圍：

- Render / Railway / DigitalOcean App Platform deployment variants。
- Grafana / Prometheus / Sentry 等外部監控平台。
- 大量壓測。
- 限價單送出後生命週期追蹤。
- Python dependency auto-merge。
- Dependabot major update auto-merge。
