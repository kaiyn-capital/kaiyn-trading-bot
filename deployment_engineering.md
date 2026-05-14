# Deployment Engineering Roadmap

更新日期：2026-05-14

本文件記錄 Kaiyn Trading Bot 進入正式部署前，偏工程化與部署流程的補強事項。核心功能、production readiness 基礎項目、CI、依賴更新管理與可重複上線流程已完成基礎版，目前可進入 DigitalOcean VPS 小額正式試運行。

## Current Status

目前已具備：

- Docker Compose 本地/部署一致環境。
- PostgreSQL、Alembic migration、async SQLAlchemy。
- Pending order DB 化與 row lock。
- 市價/限價下單流程。
- Bitget 交易所規則防呆。
- Bitget API 錯誤分類與簡短回報。
- 管理員告警、`/admin_health`、`/admin_audit`。
- Docker log rotation、Bot log rotation、DB retention。
- 每日 PostgreSQL 備份與備份還原 runbook。
- Docker-first pytest，含 opt-in PostgreSQL integration tests。
- Ruff lint / format，透過 Docker `test` service 執行。
- GitHub Actions CI，透過 Docker Compose 執行 Ruff、pytest、DB integration、py_compile 與 whitespace 檢查。
- Dependabot 每週檢查 Python packages 與 GitHub Actions，開 PR 後交由 CI 驗證。
- DigitalOcean VPS deployment runbook，涵蓋首次部署、更新、rollback、備份拉取、還原連結與故障處理。

目前建議狀態：

- 可以開始 DigitalOcean VPS 小額真實試運行。
- 正式長期放著跑前，先照 `deployment_runbook.md` 完成一次從零部署與 smoke test。

## Recommended Order

### 1. Linter / Formatter

優先加入 `ruff`，用單一工具處理 lint 與 format，避免引入過多工具。

狀態：已完成基礎版。

建議內容：

- `pyproject.toml` 的 dev optional dependency 已加入 `ruff`。
- 已新增 ruff 設定。
- 已執行一次格式化。
- 後續 CI 中加入：
  - `ruff check`
  - `ruff format --check`

原因：

- 讓後續 PR/commit 有一致格式。
- 減少重構後的風格漂移。
- 比同時導入 black/isort/flake8 更簡單。

### 2. GitHub Actions CI

先做基礎 CI，不急著自動部署。

狀態：已完成基礎版。

CI 檢查：

```bash
docker compose version
docker compose build test
docker compose up -d postgres
docker compose run --rm test ruff check .
docker compose run --rm test ruff format --check .
docker compose run --rm test python -m pytest --run-db
docker compose run --rm test python -m py_compile app/*.py app/repositories/*.py alembic/env.py alembic/versions/*.py tests/*.py
git diff --check
docker compose down -v --remove-orphans
```

DB integration 測試每次 CI 都跑，使用 Docker Compose 內建 `postgres` service，不另外設定 GitHub Actions service container。

部署策略建議：

- CI 自動測試。
- production deploy 先採手動執行。
- 暫不做 push 後自動部署，避免交易 bot 因錯誤分支或錯誤設定直接影響真金環境。

### 3. Dependabot

在 CI 建好後加入 Dependabot。建議順序放在 CI 後面，因為 Dependabot 開 PR 後需要 CI 自動驗證，否則只會增加手動檢查負擔。

狀態：已完成基礎版。

設定內容：
- 已新增 `.github/dependabot.yml`。
- 監控 Python package ecosystem。
- 監控 GitHub Actions ecosystem。
- 每週一台北時間 09:00 檢查。
- 同時最多 5 個 open PR。
- 只開 PR，不自動 merge。
- 每次 Dependabot PR 仍需通過 CI，並由你手動確認後合併。

注意事項：
- 交易 bot 不建議自動合併依賴更新。
- patch/minor update 可較快合併；major update 需額外檢查 changelog。
- 若未來 CI 加上 DB integration，也應讓 Dependabot PR 跑同一套檢查。

### 4. Deployment Runbook

新增正式部署操作文件 `deployment_runbook.md`。

狀態：已完成基礎版。

已固定第一版部署條件：

- DigitalOcean Droplet。
- Singapore region。
- Basic Premium AMD，1 vCPU / 2GB RAM / 50GB SSD。
- Ubuntu 24.04 LTS。
- 同機 Docker Compose 執行 `postgres`、`bot`、`maintenance`、`db-backup`。
- `test` service 僅用於部署前檢查，不長駐。

Runbook 已包含：

- Droplet 建立、SSH key、關閉 password login。
- DigitalOcean Cloud Firewall / UFW 基本設定。
- Docker Engine 與 Compose plugin 安裝。
- production `.env` 建立與 `POSTGRES_PORT=127.0.0.1:5432` 建議。
- 首次部署、migration、`--check-db`、服務啟動。
- 日常更新部署。
- rollback 流程。
- `/admin_health`、`/admin_audit`、`/send_signal` smoke test checklist。
- 備份拉取與 `backup_restore_runbook.md` 還原連結。
- 常見故障處理。

部署策略：

- 使用 Docker Compose。
- production VPS 上手動執行 migration。
- bot、maintenance、db-backup 服務一起啟動。
- 不在 bot 啟動時自動跑 migration。
- 不做 GitHub Actions 自動部署。

## Platform Notes

最低建議 VPS：

- DigitalOcean Basic Premium AMD。
- 1 vCPU / 2GB RAM / 50GB SSD。
- Ubuntu 24.04 LTS。
- Docker Engine + Docker Compose plugin。

正式安全建議：

- `.env` 不使用預設密碼。
- `TELEGRAM_ADMIN_IDS` 僅放實際管理員。
- Bitget API 使用最小必要權限。
- Bitget API 不開提現權限。
- 目前已決策不綁定 Bitget API IP whitelist。
- VPS firewall 只開 SSH；此 bot 通常不需要對外開 HTTP port。
- 備份不要只留在 VPS，至少定期拉到本機或雲端儲存。

## Remaining Production Gap

工程化基礎項目已完成。專案可視為接近小規模正式長期部署標準，接下來的主要工作是依照 `deployment_runbook.md` 做一次真實 VPS 部署與小額試運行。

仍不包含：

- 自動部署到 production。
- 外部監控平台。
- Grafana / Prometheus / Sentry。
- 大量壓測。
- 限價單送出後生命週期追蹤。
- Dependabot PR 自動合併。

上述項目目前不是本專案定義下的 production blocker。
