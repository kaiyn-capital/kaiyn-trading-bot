# PostgreSQL 備份還原 Runbook

本文件用於驗證 `db-backup` 服務產生的 PostgreSQL gzip SQL 備份可以實際還原。還原驗證一律使用獨立臨時 PostgreSQL container，不連到正式 `postgres_data`，避免影響正式資料。

建議頻率：

- 正式部署前至少驗證一次。
- 之後每月驗證一次，或在重大改版後驗證一次。

## 1. 確認備份狀態

查看最近一次備份狀態：

```bash
cat backups/backup_status.json
```

列出可用備份檔：

```bash
ls -lh backups/kaiyn_trading_bot_*.sql.gz
```

選擇最新備份檔，例如：

```bash
BACKUP_FILE=backups/kaiyn_trading_bot_YYYYMMDD_HHMMSS.sql.gz
```

## 2. 啟動臨時 PostgreSQL

如果先前測試留下同名 container，先清除：

```bash
docker rm -f kaiyn_restore_test
```

啟動獨立臨時 PostgreSQL 16 container：

```bash
docker run -d --name kaiyn_restore_test \
  -e POSTGRES_DB=restore_test \
  -e POSTGRES_USER=restore \
  -e POSTGRES_PASSWORD=restore \
  postgres:16-alpine
```

確認 PostgreSQL 已可連線：

```bash
docker exec kaiyn_restore_test pg_isready -U restore -d restore_test
```

若尚未 ready，等幾秒後再重試。

備份檔會包含原始資料庫 owner，例如本專案預設為 `kaiyn`。還原前先在臨時 DB 建立同名 role，避免 `OWNER TO kaiyn` 造成還原錯誤：

```bash
docker exec kaiyn_restore_test psql -U restore -d restore_test \
  -c "create role kaiyn;"
```

## 3. 還原備份

將 gzip SQL 備份還原到臨時 DB：

```bash
gunzip -c "$BACKUP_FILE" | docker exec -i kaiyn_restore_test psql -v ON_ERROR_STOP=1 -U restore -d restore_test
```

還原過程不應出現 `ERROR`。若出現錯誤，先確認備份檔是否完整、container 是否 ready，以及備份是否來自相同 PostgreSQL major version。

## 4. 驗證 schema 版本

確認 Alembic 版本：

```bash
docker exec kaiyn_restore_test psql -U restore -d restore_test \
  -c "select version_num from alembic_version;"
```

目前預期版本：

```text
20260512_0004
```

## 5. 驗證主要資料表

確認主要資料表存在：

```bash
docker exec kaiyn_restore_test psql -U restore -d restore_test \
  -c "select table_name from information_schema.tables where table_schema = 'public' order by table_name;"
```

至少應包含：

- `alembic_version`
- `users`
- `trades`
- `pending_orders`
- `channel_groups`
- `system_logs`
- `notification_logs`
- `trading_pairs`

確認主要資料表可查詢：

```bash
docker exec kaiyn_restore_test psql -U restore -d restore_test \
  -c "select 'users' as table_name, count(*) from users
      union all select 'trades', count(*) from trades
      union all select 'pending_orders', count(*) from pending_orders
      union all select 'channel_groups', count(*) from channel_groups
      union all select 'system_logs', count(*) from system_logs
      order by table_name;"
```

只要查詢可正常完成，就代表備份可讀、主要 schema 可用。筆數為 0 不一定是錯誤，需依當時環境資料量判斷。

## 6. 清除臨時環境

驗證完成後清除臨時 container：

```bash
docker rm -f kaiyn_restore_test
```

此命令只會移除臨時還原測試 container，不會影響 Docker Compose 的正式 `postgres` service 或 `postgres_data` volume。

## 7. 驗證紀錄建議

每次正式驗證後，建議記錄：

- 驗證日期。
- 使用的備份檔名。
- `alembic_version` 結果。
- 主要資料表查詢是否成功。
- 是否成功清除臨時 container。

如還原失敗，應立即檢查 `db-backup` service log 與 `backups/backup_status.json`，不要等到真正需要恢復資料時才處理。
