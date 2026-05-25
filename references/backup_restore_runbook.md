# PostgreSQL 備份與一鍵還原 Runbook

本文件整理目前低成本備份方案。主目標不是 PITR，而是讓 VPS 壞掉時，可以在新 VPS 上用最新 PostgreSQL dump 快速還原。

目前階段：

- `db-backup` 服務定期產生 gzip SQL dump。
- 每份備份都有 `.sha256` checksum。
- `backup_status.json` 保留 `/admin_health` 使用的最近備份狀態。
- `backup_manifest.json` 保留最新成功備份的檔名、時間、sha256、大小與資料庫名稱。
- `make restore-latest` 可將最新本機備份還原到 Compose PostgreSQL。
- 設定 Cloudflare R2 後，備份會先用 client-side Fernet key 加密，再上傳到 R2。
- `make disaster-restore` 可從 R2 下載最新加密備份、解密、驗 checksum，然後還原。

這不是 PITR。它是低成本「最新備份離開 VPS」方案，目標是 VPS 壞掉時能快速在新 VPS 還原。

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

若 `R2_BACKUP_ENABLED=true`，同一次備份成功後還會：

- 將 `.sql.gz` 以 `BACKUP_ENCRYPTION_KEY` 加密。
- 上傳 encrypted object 到 R2。
- 上傳 remote manifest 到 `R2_BACKUP_PREFIX/latest.json`。
- 寫入 `backups/r2_backup_status.json`。

R2 上不存 plaintext SQL dump。

## 3. Cloudflare R2 設定

`.env` 需要：

```env
R2_BACKUP_ENABLED=true
R2_ACCOUNT_ID=<cloudflare_account_id>
R2_ENDPOINT=
R2_BUCKET=kaiyn-trading-bot-backups
R2_ACCESS_KEY_ID=<r2_access_key_id>
R2_SECRET_ACCESS_KEY=<r2_secret_access_key>
R2_BACKUP_PREFIX=kaiyn-trading-bot
BACKUP_ENCRYPTION_KEY=<make_generate_backup_key_output>
```

說明：

- `R2_ENDPOINT` 通常可留空，系統會用 `R2_ACCOUNT_ID` 組成 `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`。
- 若 bucket 是 Cloudflare jurisdictional bucket，才需要手動填 `R2_ENDPOINT`。
- R2 token 建議使用 Object Read & Write，並限制到備份 bucket。
- `BACKUP_ENCRYPTION_KEY` 用 `make generate-backup-key` 產生；它不是 `ENCRYPTION_KEY`。
- `ENCRYPTION_KEY` 用於 DB 內 API credential；`BACKUP_ENCRYPTION_KEY` 用於 SQL dump 上傳前加密。兩把 key 都要離線保存。

手動測試 R2 備份：

```bash
make backup-now
cat backups/r2_backup_status.json
```

只下載最新 R2 備份、不還原：

```bash
make r2-download-latest
ls -lh backups/kaiyn_trading_bot_*.sql.gz
```

## 4. 本機一鍵還原最新備份

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

## 5. 從 R2 一鍵災難還原

在新 VPS 上，準備 repo 與 `.env` 後：

```bash
make disaster-restore
docker compose up -d bot maintenance db-backup
docker compose ps
```

如果目標 DB 已有資料且確定要覆蓋：

```bash
CONFIRM_RESTORE=YES make disaster-restore
```

`disaster-restore` 會自動：

1. 用 R2 credentials 讀取 `R2_BACKUP_PREFIX/latest.json`。
2. 下載 encrypted backup object。
3. 用 `BACKUP_ENCRYPTION_KEY` 解密。
4. 驗 encrypted 與 plaintext checksum。
5. 把解密後的 `.sql.gz` 寫到 `backups/`。
6. 呼叫 `restore-latest` 還原指定檔案。

## 6. 新 VPS 災難恢復流程

R2 流程：

```bash
cd /opt/kaiyn-trading-bot
cp .env.template .env
nano .env
make disaster-restore
docker compose up -d bot maintenance db-backup
docker compose ps
```

如果不使用 R2，仍可手動把最新備份檔放進 `backups/`：

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
- `.env` 內的 `BACKUP_ENCRYPTION_KEY` 必須是上傳 R2 時使用的 key，否則 R2 備份無法解密。
- `POSTGRES_PASSWORD` 必須和 `DATABASE_URL` 一致。
- 還原完成後再啟動 `bot`，避免 bot 在空 DB 或半還原狀態下運行。

## 7. 本機保留策略

預設：

```env
BACKUP_LOCAL_KEEP_COUNT=3
RETENTION_DAYS=30
```

也就是：

- 最多保留最近 3 份本機 SQL gzip dump。
- 同時刪除超過 `RETENTION_DAYS` 的舊備份。

此設計符合目前需求：主要使用最新備份，但保留少量 previous backup，避免最新檔剛好損壞。

R2 端目前只維護 latest manifest，不做長期歷史保留策略；本機仍保留少量 previous backup，避免最新備份剛好損壞。
