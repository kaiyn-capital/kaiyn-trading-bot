# Production Readiness Record

更新日期：2026-05-16

本文件記錄 Kaiyn Trading Bot 的 production readiness 設計與完成項目。專案定位為 Telegram + Bitget USDT-FUTURES 下單 bot，目標是在 VPS 上長期運行，並降低真金交易時的操作風險。

## Scope Boundary

系統責任邊界：

- 接收管理員或發單員發布的交易信號。
- 建立市價單或 GTC 限價單的下單確認流程。
- 送出市價單或限價單到 Bitget。
- 記錄 Bitget 是否成功接收該筆訂單。

不納入系統責任邊界：

- 限價單送出後成交狀態追蹤。
- 掛單取消、掛單過期同步、止盈自動掛單。
- 大量壓測與交易量模擬。

## Implemented Baseline

系統已具備下列 production readiness 基礎：

- PostgreSQL + SQLAlchemy asyncio。
- Alembic migration。
- Docker Compose 本地與部署一致環境。
- `bot`、`postgres`、`maintenance`、`db-backup` 服務。
- Docker log rotation 與 Bot 檔案 log 每日輪轉。
- DB retention 與每日 PostgreSQL 備份。
- Pending order 寫入 DB，並使用 row lock 避免重複確認下單。
- 市價下單與 GTC 限價掛單。
- `/send_signal` 支援備註與 UTC+8 時間戳。
- 交易所規則防呆：交易對狀態、最小下單量、最小名義價值、精度、單筆上限與止損方向檢查。
- Bitget API 錯誤分類與使用者簡短回報。
- 管理員告警與 `/admin_health` 健康檢查。
- 備份還原 runbook 與獨立臨時 PostgreSQL 還原驗證流程。
- 操作審計與 `/admin_audit` 查詢。
- Docker-first pytest，包含 PostgreSQL integration tests。
- GitHub Actions CI，涵蓋 lockfile、Alembic migration/model、Ruff、mypy、PostgreSQL integration、coverage output、`py_compile` 與 whitespace 檢查。
- GHCR image pipeline 與 VPS SSH CD，經 `production` environment approval 後以 image digest 部署到 DigitalOcean VPS。
- DigitalOcean、SSH CD、backup/restore 與 deployment engineering 文件，覆蓋上線、更新、rollback 與災難恢復驗證。

## Trading Safety

下單預覽與確認送單前都會執行交易安全檢查：

- 交易對必須存在於 Bitget USDT-FUTURES。
- 交易對狀態必須可交易。
- 下單數量必須符合最小下單量、數量精度與單筆上限。
- 下單名義價值必須符合交易所最小值。
- 限價單價格必須符合價格精度與 price step。
- Long 止損必須低於計算價格。
- Short 止損必須高於計算價格。
- API credential 必須完整。

風控邊界：

- 系統不設定 1R 全域上限。
- 系統不設定止損距離百分比上下限。
- 交易權限與帳戶風控由 Bitget 送單結果判定。

## Bitget API Error Handling

Bitget/API 錯誤會統一分類並轉成簡短使用者訊息。

分類範圍：

- 使用者 API 設定或權限問題。
- 交易對問題。
- 交易所拒單。
- 交易所或網路暫時異常。
- 未知錯誤。

紀錄策略：

- 使用者只看到簡短原因。
- `trades.error_message`、`pending_orders.error_message` 與 `system_logs.extra_data` 保留分類、raw code/message 與上下文。
- 系統不自動 retry 送單，避免重複下單。

## Admin Alerts And Health Checks

管理員告警與健康檢查覆蓋下列項目：

- Bot 啟動成功或啟動失敗。
- DB 連線異常。
- Bitget API 連續失敗達門檻。
- maintenance cleanup 執行失敗。
- db-backup 備份失敗。
- `/admin_health` 查看 DB、Bot、備份、cleanup、Bitget API 與近期錯誤狀態。

## Backup And Restore

備份制度：

- `db-backup` 定期產生 gzip SQL 備份。
- 備份檔輸出到 `backups/`。
- 備份檔預設保留最近 3 份，並刪除超過 retention window 的舊備份。
- 每份備份產生 `.sha256` checksum。
- `backup_status.json` 記錄最近一次備份結果。
- `backup_manifest.json` 記錄最新成功備份的檔名、時間、sha256、大小與資料庫名稱。
- 若 `R2_BACKUP_ENABLED=true`，備份會以 `BACKUP_ENCRYPTION_KEY` 加密後上傳 Cloudflare R2。
- `r2_backup_status.json` 記錄最近一次 R2 上傳結果。

還原流程：

- 還原流程記錄於 [backup_restore_runbook.md](backup_restore_runbook.md)。
- `make restore-latest` 會驗 checksum、檢查目標 DB 是否非空、還原 dump、執行 migration 與 DB health check。
- `make disaster-restore` 會從 R2 下載最新 encrypted backup、解密、驗 checksum，再呼叫本機還原流程。
- 目標 DB 非空時必須明確設定 `CONFIRM_RESTORE=YES`。

## Core Flow Tests

測試框架：

- pytest。
- Docker Compose `test` service。
- 預設測試不連 Telegram、不呼叫 Bitget 真實 API。
- PostgreSQL integration tests 使用 Docker network 內的 `postgres:5432`。
- DB integration 測試使用獨立 schema，測完自動刪除。

測試覆蓋：

- `/send_signal` 參數解析，包含 TP 與備註文字。
- Long/Short 掛單價格選擇。
- 掛單價可能立即成交時切換市價確認。
- 1R 倉位計算。
- 交易安全防呆規則。
- Pending order confirm/cancel/expired/executed/failed 狀態流程。
- Pending order repository PostgreSQL integration。

## Permission And Audit

操作審計使用既有 `system_logs`：

- `module="audit"`。
- `function` 記錄操作類型。
- `extra_data` 保存結構化摘要。

審計範圍：

- 新增發單員。
- 頻道新增、重新啟用、刪除。
- Telegram topic 設定與清除。
- 廣播與指定頻道發送摘要。
- 發送交易信號摘要。
- 點擊市價/掛單。
- 建立、確認、取消、過期、重複確認 pending order。
- 下單成功與失敗原因。

資料保護：

- 不保存 API key、secret、passphrase。
- 不保存完整 Bitget response。
- 不保存完整下單 payload。
- 廣播與手動發送只保存訊息長度與短預覽。

## Verification Commands

完整驗證流程：

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

部署 smoke test：

```bash
docker compose build bot
docker compose up -d bot
docker compose logs --tail 40 bot
```

Schema 變更驗證流程：

```bash
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot python -m app.main --check-db
```
