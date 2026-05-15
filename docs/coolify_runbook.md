# Coolify Deployment Runbook

本文件說明 Kaiyn Trading Bot 使用 Coolify 作為 VPS 上的 deployment executor。GHCR image pipeline 仍由 GitHub Actions 負責，Coolify 負責拉取已通過 CI 的 image、執行部署、保存環境變數與提供 deployment dashboard。

部署模型：

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

- Source：GitHub repository `kylekkkk61/kaiyn-trading-bot`
- Compose file：`compose.coolify.yml`
- Auto deploy：關閉
- Deployment trigger：使用 API / webhook，由 GitHub Actions 控制
- Public HTTP domain：不需要，Bot 沒有 HTTP endpoint

Coolify application 應部署在既有 VPS / Oracle VM 上。若 VM 已用手動 Docker Compose 跑過 production DB，搬到 Coolify stack 前先做 SQL backup，並用 [backup_restore_runbook.md](backup_restore_runbook.md) 還原到 Coolify-managed PostgreSQL volume。

## 2. Required Coolify Variables

Coolify application variables 必須包含：

```text
BOT_IMAGE=ghcr.io/kylekkkk61/kaiyn-trading-bot:main
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
```

`BOT_IMAGE` 會由 GitHub Actions release workflow 自動更新為 `ghcr.io/kylekkkk61/kaiyn-trading-bot:sha-<commit>`。

## 3. Migration Command

在 Coolify application 設定 pre-deployment command：

```bash
alembic upgrade head
```

pre-deployment command container 指定：

```text
bot
```

這讓每次 Coolify deployment 都在啟動新版 Bot 前套用 Alembic migration。Bot 啟動流程本身仍不自動 migration。

## 4. GitHub Environment Secrets

GitHub `production` environment 需要設定：

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

SSH secrets 不再由 release workflow 使用；SSH manual deployment 只作 fallback。

## 5. GitHub Actions Deployment

`.github/workflows/release.yml` 會執行：

1. build and push GHCR image。
2. 等待 `production` environment approval。
3. `PATCH /api/v1/applications/{uuid}/envs` 更新：

   ```text
   BOT_IMAGE=ghcr.io/kylekkkk61/kaiyn-trading-bot:sha-<commit>
   ```

4. `GET $COOLIFY_WEBHOOK` 觸發 Coolify deploy。

若 Coolify API 或 webhook 回傳非 2xx，workflow 會失敗，不會 fallback 到 SSH deploy。

## 6. Manual Deploy And Rollback

手動部署指定 image：

1. 在 Coolify application variables 將 `BOT_IMAGE` 改成：

   ```text
   ghcr.io/kylekkkk61/kaiyn-trading-bot:sha-<commit>
   ```

2. 按 Deploy。

Rollback 使用上一個已知可用 commit tag：

```text
ghcr.io/kylekkkk61/kaiyn-trading-bot:sha-<known-good-commit>
```

Alembic migration 不自動 downgrade。若新 migration 造成資料庫不可用，依 [backup_restore_runbook.md](backup_restore_runbook.md) 還原資料庫。

## 7. Verification

Coolify deploy 完成後：

- 確認 `bot`、`maintenance`、`db-backup`、`postgres` 都是 running。
- 查看 Bot logs 沒有 startup failure。
- Telegram 執行 `/admin_health`。
- 確認 `db-backup` volume 內有 `backup_status.json` 與 `.sql.gz` 備份。

GitHub Actions release run 應顯示：

- `Build and publish GHCR image` 成功。
- `Deploy production via Coolify` 成功。
- 無 Node.js deprecation warning。

## 8. Operational Notes

- Coolify 是部署 executor，不取代 GHCR image pipeline。
- GHCR package 建議保持 public；若改 private，需要在 Coolify/VPS 設定 GHCR pull credentials。
- Coolify application variables 屬於 production secrets，不提交到 git。
- `compose.coolify.yml` 不對外公開 PostgreSQL port。
- SSH + `make deploy-image` 流程保留為 disaster fallback。

References:

- Coolify deploy API: https://coolify.io/docs/api-reference/api/operations/deploy-by-tag-or-uuid
- Coolify application env API: https://coolify.io/docs/api-reference/api/operations/update-env-by-application-uuid
- Coolify GitHub Actions: https://coolify.io/docs/applications/ci-cd/github/actions
