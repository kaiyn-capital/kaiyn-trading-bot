# Coolify Deployment Runbook

本文件保留 Kaiyn Trading Bot 的 optional Coolify deployment variant。正式 production CD 主線為 GHCR + VPS SSH CD，透過 `.github/workflows/release.yml` 連線 VPS 並執行 `make deploy-image`。Coolify 可作為未來替代 executor，用於拉取已通過 CI 的 image、執行部署、保存環境變數與提供 deployment dashboard。

可選 Coolify 部署模型：

```text
CI passed
-> GitHub Actions build multi-arch GHCR image
-> production environment approval
-> GitHub Actions updates Coolify BOT_IMAGE
-> GitHub Actions triggers Coolify deploy webhook
-> Coolify deploys compose.coolify.yml
```

## 1. Coolify Resource

在 Coolify 建立 Docker Compose application：

- Source：GitHub repository `kaiyn-capital/kaiyn-trading-bot`
- Compose file：`compose.coolify.yml`
- Auto deploy：關閉
- Deployment trigger：使用 API / webhook，由 GitHub Actions 控制
- Public HTTP domain：不需要，Bot 沒有 HTTP endpoint

Coolify application 應部署在既有 DigitalOcean Droplet 上。若 Droplet 已用手動 Docker Compose 跑過 production DB，搬到 Coolify stack 前先做 SQL backup，並用 [backup_restore_runbook.md](backup_restore_runbook.md) 還原到 Coolify-managed PostgreSQL volume。

若 GHCR package 是 private，Coolify 或所在主機的 Docker runtime 必須設定可讀取 `ghcr.io/kaiyn-capital/kaiyn-trading-bot` 的 registry credentials。需要的 GitHub token 權限至少包含 `read:packages`。

## 2. Required Coolify Variables

Coolify application variables 必須包含：

```text
BOT_IMAGE=ghcr.io/kaiyn-capital/kaiyn-trading-bot:main
TELEGRAM_BOT_TOKEN=<production telegram token>
TELEGRAM_ADMIN_IDS=<comma separated admin ids>
ENCRYPTION_KEY=<fernet key>
POSTGRES_DB=kaiyn_trading_bot
POSTGRES_USER=kaiyn
POSTGRES_PASSWORD=<strong password>
DATABASE_URL=postgresql+asyncpg://kaiyn:<strong password>@postgres:5432/kaiyn_trading_bot
BITGET_API_URL=https://api.bitget.com
DEBUG=False
LOG_LEVEL=INFO
RETENTION_DAYS=30
MAINTENANCE_INTERVAL_SECONDS=86400
BACKUP_INTERVAL_SECONDS=86400
HEALTHCHECK_INTERVAL_SECONDS=300
ADMIN_ALERT_COOLDOWN_SECONDS=1800
ADMIN_NOTIFY_STARTUP_SUCCESS=True
BITGET_ALERT_FAILURE_THRESHOLD=3
BITGET_ALERT_WINDOW_SECONDS=600
BACKUP_STALE_HOURS=36
MAINTENANCE_STALE_HOURS=36
SIGNAL_CHART_ENABLED=true
SIGNAL_CHART_GRANULARITY=1H
SIGNAL_CHART_CANDLE_LIMIT=120
SIGNAL_CHART_TIMEOUT_SECONDS=8
```

`BOT_IMAGE` 會由 GitHub Actions release workflow 自動更新為 `ghcr.io/kaiyn-capital/kaiyn-trading-bot:sha-<commit>`。

## 3. Database Migration

`compose.coolify.yml` 內建 `migrate` 一次性服務：

```text
postgres healthy
-> migrate runs alembic upgrade head
-> bot and maintenance start after migrate exits successfully
```

Coolify 不需要額外設定 pre-deployment command。每次 deployment 由 compose dependency gate 確保新版 Bot 啟動前已套用 Alembic migration。

`migrate` container 成功後會以 exited 狀態保留，這是預期行為。`bot`、`maintenance` 與 `db-backup` 才是長駐服務。

首次部署若看到 `relation "system_logs" does not exist` 或 `relation "pending_orders" does not exist`，代表該 deployment 使用的 compose 尚未執行 migration gate。更新到包含 `migrate` service 的 repo 版本後重新 deploy。

## 4. GitHub Environment Secrets

只有切換到 Coolify executor 時，GitHub `production` environment 才需要設定：

```text
COOLIFY_TOKEN
COOLIFY_API_BASE_URL
COOLIFY_APPLICATION_UUID
COOLIFY_WEBHOOK
```

說明：

- `COOLIFY_TOKEN`：Coolify `Keys & Tokens` 建立的 API token。
- `COOLIFY_API_BASE_URL`：Coolify instance base URL，例如 `https://coolify.example.com`，不要包含 `/api/v1`。
- `COOLIFY_APPLICATION_UUID`：Coolify application UUID。
- `COOLIFY_WEBHOOK`：Coolify deployment webhook URL。

正式 SSH CD 主線使用 `PRODUCTION_SSH_*` secrets；Coolify secrets 不屬於目前主線必要設定。

## 5. GitHub Actions Deployment

目前 `.github/workflows/release.yml` 使用 SSH executor，不呼叫 Coolify API。若切換到本可選方案，release workflow 可改為執行：

1. build and push GHCR image。
2. 等待 `production` environment approval。
3. `PATCH /api/v1/applications/{uuid}/envs` 更新：

   ```text
   BOT_IMAGE=ghcr.io/kaiyn-capital/kaiyn-trading-bot:sha-<commit>
   ```

4. `GET $COOLIFY_WEBHOOK` 觸發 Coolify deploy。

若 Coolify API 或 webhook 回傳非 2xx，workflow 應直接失敗，不 fallback 到 SSH deploy。

## 6. Manual Deploy And Rollback

手動部署指定 image：

1. 在 Coolify application variables 將 `BOT_IMAGE` 改成：

   ```text
   ghcr.io/kaiyn-capital/kaiyn-trading-bot:sha-<commit>
   ```

2. 按 Deploy。

Rollback 使用上一個已知可用 commit tag：

```text
ghcr.io/kaiyn-capital/kaiyn-trading-bot:sha-<known-good-commit>
```

Alembic migration 不自動 downgrade。若新 migration 造成資料庫不可用，依 [backup_restore_runbook.md](backup_restore_runbook.md) 還原資料庫。

## 7. Verification

Coolify deploy 完成後：

- 確認 `postgres`、`bot`、`maintenance`、`db-backup` 都是 running。
- 確認 `migrate` 已成功完成，並且 exit code 為 0。
- 查看 Bot logs 沒有 startup failure。
- Telegram 執行 `/admin_health`。
- 確認 `db-backup` volume 內有 `backup_status.json` 與 `.sql.gz` 備份。

在 VPS 上檢查 Docker volume 時使用 Docker 指令：

```bash
docker volume ls
docker volume inspect <volume_name>
```

`postgres_data`、`bot_logs`、`db_backups` 是 compose volume 名稱，不是 shell command。

GitHub Actions release run 應顯示：

- `Build and publish GHCR image` 成功。
- Coolify executor 啟用時，`Deploy production via Coolify` 成功。
- 無 Node.js deprecation warning。

## 8. Operational Notes

- Coolify 是可選部署 executor，不取代 GHCR image pipeline。
- GHCR package 建議保持 public；若改 private，需要在 Coolify/VPS 設定 GHCR pull credentials。
- Coolify application variables 屬於 production secrets，不提交到 git。
- `compose.coolify.yml` 不對外公開 PostgreSQL port。
- SSH + `make deploy-image` 是目前 production CD 主線；Coolify 切換前需先停止 SSH CD 或避免同一個 Telegram bot token 同時啟動兩套 runtime。

References:

- Coolify deploy API: https://coolify.io/docs/api-reference/api/operations/deploy-by-tag-or-uuid
- Coolify application env API: https://coolify.io/docs/api-reference/api/operations/update-env-by-application-uuid
- Coolify GitHub Actions: https://coolify.io/docs/applications/ci-cd/github/actions
