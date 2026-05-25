# PostgreSQL 備份與一鍵還原 Runbook

本文件整理目前低成本備份方案。主目標不是 PITR，而是讓 VPS 壞掉時，可以在新 VPS 上用最新 PostgreSQL dump 快速還原。

目前階段：

- `db-backup` 服務定期產生 gzip SQL dump。
- 每份備份都有 `.sha256` checksum。
- `backup_status.json` 保留 `/admin_health` 使用的最近備份狀態。
- `backup_manifest.json` 保留最新成功備份的檔名、時間、sha256、大小與資料庫名稱。
- `make restore-latest` 可將最新本機備份還原到 Compose PostgreSQL。

下一階段會接 Cloudflare R2，讓最新備份離開 VPS。

## 1. 確認備份狀態

查看最近一次備份狀態：

```bash
cat backups/backup_status.json
```

查看最新成功備份 manifest：

```bash
cat backups/backup_manifest.json
```

列出本機備份：

```bash
ls -lh backups/kaiyn_trading_bot_*.sql.gz
ls -lh backups/kaiyn_trading_bot_*.sql.gz.sha256
```

## 2. 手動立即備份

平常 `db-backup` 會依 `BACKUP_INTERVAL_SECONDS` 自動備份。需要在升級或操作前先手動打一份：

```bash
make backup-now
```

這會使用同一套 `db-backup` container 與 `scripts/backup_database.sh`，產生：

- `backups/kaiyn_trading_bot_YYYYMMDD_HHMMSS.sql.gz`
- `backups/kaiyn_trading_bot_YYYYMMDD_HHMMSS.sql.gz.sha256`
- `backups/backup_status.json`
- `backups/backup_manifest.json`

備份使用 `pg_dump --no-owner --no-privileges`，降低在新 VPS、不同 DB owner 或臨時 DB 還原時的角色相容性問題。

## 3. 本機一鍵還原最新備份

危險：還原會改寫目標 PostgreSQL database。若 DB 已有資料，必須明確加 `CONFIRM_RESTORE=YES`。

在空 DB 或新 VPS 上：

```bash
make restore-latest
```

在既有非空 DB 上確認覆蓋：

```bash
CONFIRM_RESTORE=YES make restore-latest
```

指定某一份備份：

```bash
BACKUP_FILE=backups/kaiyn_trading_bot_YYYYMMDD_HHMMSS.sql.gz CONFIRM_RESTORE=YES make restore-latest
```

`restore-latest` 會自動：

1. 找最新 `backups/kaiyn_trading_bot_*.sql.gz`。
2. 若 `.sha256` 存在，先驗 checksum。
3. 啟動 Compose `postgres`。
4. 檢查目標 DB 是否已有資料表。
5. 非空 DB 且沒有 `CONFIRM_RESTORE=YES` 時拒絕還原。
6. `CONFIRM_RESTORE=YES` 時先重建 `public` schema。
7. 將 gzip SQL dump 還原到 Compose `postgres`。
8. 執行 `alembic upgrade head`。
9. 執行 `python -m app.main --check-db`。

## 4. 新 VPS 災難恢復流程

在尚未接 Cloudflare R2 前，新 VPS 仍需要你先把最新備份檔放進 `backups/`：

```bash
scp kaiyn_trading_bot_YYYYMMDD_HHMMSS.sql.gz deploy@<new-vps>:/opt/kaiyn-trading-bot/backups/
scp kaiyn_trading_bot_YYYYMMDD_HHMMSS.sql.gz.sha256 deploy@<new-vps>:/opt/kaiyn-trading-bot/backups/
```

然後在新 VPS：

```bash
cd /opt/kaiyn-trading-bot
cp .env.template .env
nano .env
make restore-latest
docker compose up -d bot maintenance db-backup
docker compose ps
```

注意：

- `.env` 內的 `ENCRYPTION_KEY` 必須是原 production key，否則 DB 內 encrypted API credentials 無法解密。
- `POSTGRES_PASSWORD` 必須和 `DATABASE_URL` 一致。
- 還原完成後再啟動 `bot`，避免 bot 在空 DB 或半還原狀態下運行。

## 5. 本機保留策略

預設：

```env
BACKUP_LOCAL_KEEP_COUNT=3
RETENTION_DAYS=30
```

也就是：

- 最多保留最近 3 份本機 SQL gzip dump。
- 同時刪除超過 `RETENTION_DAYS` 的舊備份。

此設計符合目前需求：主要使用最新備份，但保留少量 previous backup，避免最新檔剛好損壞。

## 6. Cloudflare R2 下一階段

下一個 PR 會接 Cloudflare R2：

- 備份成功後上傳 encrypted latest backup。
- 上傳 checksum 與 manifest。
- 新增 `make disaster-restore`，從 R2 下載最新備份並還原。

需要你手動準備：

- Cloudflare 帳號。
- R2 bucket。
- R2 access key / secret key。
- 備份 client-side encryption key。

在 R2 尚未接上前，不要把 VPS 本機 `backups/` 當成唯一災備來源。至少在重要變更前後手動拉一份最新備份到本機或雲端。
