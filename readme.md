# Kaiyn Trading Bot

Kaiyn Trading Bot 是整合 Telegram 與 Bitget U 本位合約交易的機器人。使用者可透過 Telegram 設定 Bitget API 憑證、查詢狀態與餘額，並在管理員或發單員發布交易信號後，用按鈕進入定 R 風險下單流程。

> 風險提醒：本專案會連接真實交易所 API 並送出合約訂單。Bitget API 建議只授予交易權限，不要授予提幣權限。

## 功能概覽

- Telegram Bot 長輪詢啟動與指令選單
- Bitget API Key、Secret Key、Passphrase 加密儲存
- PostgreSQL async database access
- Alembic schema migration
- Docker Compose 本地/部署一致環境
- U 本位合約 USDT 餘額查詢
- 固定風險金額 1R 設定
- 交易信號支援市價下單與 GTC 限價掛單
- 交易信號支援備註文字與 UTC+8 時間戳
- 下單前檢查 Bitget 合約交易對狀態、最小下單量、最小名義價值、精度與單筆上限
- Bitget API 錯誤分類，使用者看到簡短原因，管理員 log 保留 raw code/message
- 管理員與發單員權限管理
- 頻道或群組管理與交易信號轉發
- Telegram forum topic 指定轉發
- Pending order 寫入 PostgreSQL，Bot 重啟後仍可確認尚未過期的訂單
- 管理員告警、`/admin_health` 健康檢查、每日清理與備份
- 備份還原 runbook 與本地還原驗證流程

## 技術棧

- Python 3.11
- python-telegram-bot 20.6
- SQLAlchemy asyncio
- PostgreSQL
- Alembic
- asyncpg
- httpx
- cryptography Fernet
- Docker Compose
- pytest（dev optional dependency，僅測試 image 安裝）

## 專案結構

```text
.
├── alembic/
│   ├── env.py
│   └── versions/            # Alembic migration scripts
├── app/
│   ├── __init__.py
│   ├── main.py              # CLI 入口、啟動流程、初始化工具
│   ├── bot.py               # Telegram Bot handler 註冊與 lifecycle
│   ├── bot_account_handlers.py # /start、/status、/balance、/setapi、/settings
│   ├── bot_admin_handlers.py # 管理員 handler mixin 聚合入口
│   ├── bot_admin_core.py  # /admin、/admin_users、/add_trader
│   ├── bot_admin_channels.py # 頻道、群組、topic 管理
│   ├── bot_admin_messaging.py # 管理員廣播與指定頻道發送
│   ├── bot_admin_monitoring.py # /admin_health、/admin_audit
│   ├── bot_order_handlers.py # /send_signal、pending order、下單確認流程
│   ├── bot_keyboards.py     # Telegram inline keyboard builders
│   ├── bot_messages.py      # Bot 訊息文字與格式化
│   ├── bot_states.py        # API 設定 conversation state 常數
│   ├── order_flow.py        # 交易信號解析、下單預覽與執行流程
│   ├── bitget_api.py        # Bitget API client 與交易管理器
│   ├── bitget_errors.py     # Bitget/API 錯誤分類與使用者訊息 mapping
│   ├── admin_alerts.py      # 管理員告警、cooldown、Bitget 連續錯誤門檻
│   ├── health.py            # /admin_health 與備份/維護狀態整理
│   ├── config.py            # 環境變數設定與驗證
│   ├── database.py          # PostgreSQL async manager 與 repo getter façade
│   ├── encryption.py        # API 憑證加解密
│   ├── models.py            # SQLAlchemy models
│   └── repositories/        # User/Trade/PendingOrder/Channel/SystemLog repositories
├── tests/                   # pytest 純邏輯、handler 與 DB integration 測試
├── backups/                 # 本機/部署備份輸出目錄，git ignored
├── logs/                    # Bot log 與 alert state，git ignored
├── alembic.ini
├── backup_restore_runbook.md
├── compose.yml
├── Dockerfile
├── AGENTS.md
├── production_readiness.md
├── pyproject.toml
├── restart_bot.sh
└── .env.template
```

## 環境設定

建立 `.env`：

```bash
cp .env.template .env
```

產生 Fernet 加密金鑰：

```bash
python3 -m app.main --generate-key
```

將輸出的值填入 `.env` 的 `ENCRYPTION_KEY`。

必要環境變數：

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_ADMIN_IDS=123456789,987654321

POSTGRES_DB=kaiyn_trading_bot
POSTGRES_USER=kaiyn
POSTGRES_PASSWORD=kaiyn
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://kaiyn:kaiyn@postgres:5432/kaiyn_trading_bot

ENCRYPTION_KEY=your_fernet_key_here
BITGET_API_URL=https://api.bitget.com
DEBUG=False
LOG_LEVEL=INFO
MAX_DAILY_TRADES=10
MAX_POSITION_SIZE=1000
RETENTION_DAYS=30
MAINTENANCE_INTERVAL_SECONDS=86400
BACKUP_INTERVAL_SECONDS=86400
ADMIN_NOTIFY_STARTUP_SUCCESS=True
HEALTHCHECK_INTERVAL_SECONDS=300
ADMIN_ALERT_COOLDOWN_SECONDS=1800
BITGET_ALERT_FAILURE_THRESHOLD=3
BITGET_ALERT_WINDOW_SECONDS=600
BACKUP_STALE_HOURS=36
MAINTENANCE_STALE_HOURS=36
```


## 本地開發與測試

Python 套件只維護 `pyproject.toml`，沒有 `requirements.txt`。Runtime 依賴與 Docker 安裝流程也都以 `pyproject.toml` 為準。

建置測試 image：

```bash
docker compose build test
```

執行 lint 與格式檢查：

```bash
docker compose run --rm test ruff check .
docker compose run --rm test ruff format --check .
```

手動格式化：

```bash
docker compose run --rm test ruff check --fix .
docker compose run --rm test ruff format .
```

執行預設測試：

```bash
docker compose run --rm test python -m pytest
```

預設測試不會連線 Telegram、不會呼叫 Bitget 真實 API；DB integration 測試會被自動跳過。測試 service 透過 Docker network 使用 `postgres:5432`，不依賴本機 `localhost:5432`。

執行 PostgreSQL integration 測試：

```bash
docker compose up -d postgres
docker compose run --rm test python -m pytest --run-db -m integration
```

執行全部測試：

```bash
docker compose run --rm test python -m pytest --run-db
```

DB integration 測試會在 PostgreSQL 裡建立獨立測試 schema，測完自動刪除，不會清空 `public` schema。
本機 `python3 -m pytest` 可作為開發 shortcut，但主要驗證流程以 Docker Compose 為準。
若要使用本機 shortcut，可先執行 `pip install -e ".[dev]"`。

## GitHub Actions CI

本專案提供基礎 CI：`.github/workflows/ci.yml`。

觸發條件：

- push 到 `main`
- PR 指向 `main`
- 手動 `workflow_dispatch`

CI 使用 Docker Compose 執行，不使用 production secrets，也不連線 Telegram 或 Bitget 真實 API。每次 CI 會檢查：

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

目前測試覆蓋重點：

- `/send_signal` 解析、TP 與備註。
- 市價/掛單預覽、立即成交切市價、1R 倉位計算。
- Bitget 合約規則防呆與錯誤分類。
- Pending order confirm/cancel/expired/executed/failed 狀態流程。
- 管理頻道、topic 設定、API 設定流程。
- 管理員告警、backup/maintenance health report。

## 本地與部署流程

本地測試與 VPS 部署使用同一套 Docker Compose 流程。

建置映像：

```bash
docker compose build
```

啟動 PostgreSQL：

```bash
docker compose up -d postgres
```

套用 migration：

```bash
docker compose run --rm bot alembic upgrade head
```

檢查資料庫連線：

```bash
docker compose run --rm bot python -m app.main --check-db
```

啟動 Bot：

```bash
docker compose up -d bot
```

啟動長期維護與備份：

```bash
docker compose up -d maintenance db-backup
```

查看 log：

```bash
docker compose logs -f bot
```

查看服務狀態：

```bash
docker compose ps
```

重啟 Bot：

```bash
docker compose restart bot
```

`restart_bot.sh` 僅保留作為舊版輔助腳本；正式本地測試與部署建議以 `docker compose` 指令為準。

## 長期維護

部署後建議同時啟動 `maintenance` 與 `db-backup` 服務，避免舊資料、檔案 log、Docker log 或備份檔長期撐滿磁碟。

保留策略：

- Docker container logs：每個服務單檔 10MB，最多 5 個檔案。
- Bot 檔案日誌 `logs/app.log`：每日輪轉，保留 30 天。
- PostgreSQL 累積紀錄：`system_logs`、`notification_logs`、`pending_orders`、`trades` 保留 30 天。
- PostgreSQL 備份：每天建立 gzip SQL 備份到 `./backups`，保留 30 天。
- 管理員告警：Bot 啟動、DB/backup/cleanup 異常、Bitget API 連續暫時異常會推送到 `TELEGRAM_ADMIN_IDS`。
- 健康檢查：管理員可用 `/admin_health` 查看 DB、backup、cleanup、Bitget API 與近期錯誤狀態。
- 操作審計：管理員、發單員與下單關鍵操作會以結構化摘要寫入 `system_logs`，同樣保留 30 天。
- 備份還原驗證：正式部署前至少依照 [backup_restore_runbook.md](backup_restore_runbook.md) 驗證一次，之後每月或重大改版後驗證一次。

手動 dry-run 檢查會清理多少資料：

```bash
docker compose run --rm bot python -m app.main --cleanup-retention --dry-run
```

手動執行清理：

```bash
docker compose run --rm bot python -m app.main --cleanup-retention
```

查看維護與備份服務：

```bash
docker compose ps
docker compose logs maintenance
docker compose logs db-backup
ls -lh backups
cat backups/backup_status.json
```

備份還原驗證：

```bash
cat backup_restore_runbook.md
```

## Telegram 指令

一般使用者：

- `/start`：開始使用機器人並顯示主選單。
- `/help`：查看指令說明。
- `/setapi`：依序輸入 Bitget API Key、Secret Key、Passphrase。
- `/status`：檢查 API 連線狀態並顯示 Bitget UID。
- `/balance`：查詢 U 本位合約帳戶 USDT 餘額。
- `/settings`：設定固定風險金額 1R。

管理員：

- `/admin`：管理員面板與系統統計。
- `/admin_health`：查看系統健康狀態、備份、維護任務與近期錯誤。
- `/admin_audit [數量]`：查看近期操作審計，預設 10 筆，最多 30 筆。
- `/admin_users`：查看活躍使用者列表。
- `/admin_channels`：查看與管理頻道或群組。
- `/add_channel @username 描述`：新增公開頻道或群組。
- `/add_channel -1001234567890 描述`：新增私人群組或頻道 ID。
- `/admin_broadcast 訊息內容`：向所有已管理頻道或群組廣播訊息。
- `/send_to_channel 目標 訊息內容`：向指定頻道或群組發送訊息。
- `/set_channel_topic 頻道編號 topic_id [話題名稱]`：設定交易信號轉發到指定 Telegram topic。
- `/clear_channel_topic 頻道編號`：清除指定 topic，恢復轉發到群組本身。
- `/add_trader Telegram_ID`：將指定使用者設為發單員。
- `/send_signal ...`：發送交易信號。

發單員：

- `/send_signal ...`：發送交易信號到已啟用自動轉發的頻道或群組。

## 操作審計

`/admin_audit [數量]` 可查詢最近的正式操作事件，包含新增發單員、頻道管理、廣播、發送信號、點擊市價/掛單、pending order 確認/取消、下單成功與失敗原因。

審計資料寫入 `system_logs`，`module` 固定為 `audit`，資料保留 30 天。審計內容採摘要化策略：交易信號保留 symbol、方向、entry、SL、TP 與備註；廣播和手動發送只保留訊息長度與短預覽；不保存 API key、secret、passphrase、完整 Bitget response、完整下單 payload。

## Telegram Topic 轉發

若管理群組是 Telegram forum supergroup，可讓交易信號轉發到指定話題。

流程：

1. 先用 `/add_channel` 加入群組。
2. 用 `/admin_channels` 查看頻道編號。
3. 管理員自行取得 Telegram `message_thread_id`。
4. 設定指定 topic：

```text
/set_channel_topic 1 12345 交易信号
```

5. 之後 `/send_signal` 轉發到該群組時，會帶上 `message_thread_id`。

清除 topic：

```text
/clear_channel_topic 1
```

`[話題名稱]` 是管理員自訂備註名稱，只用於 `/admin_channels` 顯示，不需要與 Telegram 話題實際名稱完全一致。

目前指定 topic 只套用於 `/send_signal` 交易信號自動轉發；`/admin_broadcast` 與 `/send_to_channel` 維持發到群組本身。

## 交易信號格式

```text
/send_signal 交易對 方向 低進場價 高進場價 止損價 止盈價1 [止盈價2] [止盈價3] [止盈價4] [備註文字]
```

範例：

```text
/send_signal BTCUSDT long 115000 115500 114200 117500 120500 123500
/send_signal ETHUSDT short 3200 3250 3300 3100 3000 2900 等待回踩后执行
```

格式規則：

- `方向` 僅支援 `long` 或 `short`。
- 止盈價從第 6 個參數開始解析；第一個無法解析為數字的參數與後續內容會合併為備註。
- 備註會顯示在信號的 `SL` 下方。
- 信號底部時間戳使用 UTC+8。

信號按鈕與 Bot 介面文字目前使用簡體中文，例如「市价下单」、「挂单」、「确认下单」。

## 下單流程

1. 管理員或發單員使用 `/send_signal` 發送交易信號。
2. Bot 將信號轉發到已啟用的頻道或群組，並附上「市价下单」與「挂单」按鈕。
3. 使用者點擊任一下單方式後，Bot 會檢查 API 設定與固定風險金額 1R。
4. Bot 取得 Bitget 當前市價與 USDT-FUTURES 合約規則，計算倉位名義價值與數量。
5. Bot 檢查交易對狀態、最小下單量、最小名義價值、數量/價格精度、單筆上限與止損方向。
6. 驗證通過後，Bot 將待確認訂單寫入 `pending_orders`，並發送確認/取消按鈕。
7. 使用者確認後，Bot 使用 row lock 將 pending order 標為 `processing`，避免重複下單。
8. 送單前 Bot 會重新取得市價與合約規則再驗證一次；若規則已不符合，會標記為 `failed` 並提示重新點擊信號下單。
9. Bitget 下單完成後，Bot 更新 `trades` 與 `pending_orders` 狀態。

下單方式：

- 市價下單：使用目前市價計算 1R，送出 market order，成功後 `trades.status` 記為 `filled`。
- 掛單：Long 使用 entry 區間較高點，Short 使用 entry 區間較低點，送出 GTC limit order 並同時帶止損，成功後 `trades.status` 記為 `pending`。
- 若掛單價格已可能立即成交，Bot 會切換到市價下單確認流程並提示原因。

倉位計算概念：

```text
止損距離百分比 = abs(計算價格 - 止損價) / 計算價格
倉位名義價值 = 固定風險金額 1R / 止損距離百分比
交易數量 = 倉位名義價值 / 計算價格
```

市價下單的計算價格為目前市價；掛單的計算價格為掛單價。

交易安全防呆：

- 交易對必須存在於 Bitget `USDT-FUTURES` 且狀態為 `normal`。
- 下單數量需符合 `minTradeNum`、`sizeMultiplier`、`volumePlace` 與單筆上限。
- 掛單價格需符合 `pricePlace` 與 `priceEndStep`。
- 下單名義價值需符合 `minTradeUSDT`。
- Long 止損必須低於計算價格；Short 止損必須高於計算價格。
- 本專案目前不額外設定 1R 全域上限，也不額外設定止損距離百分比上下限。

錯誤處理：

- API key、權限、簽名、IP whitelist 等問題會回報為 API 設定或權限異常。
- 交易對不存在或不可交易會回報為交易對問題。
- Bitget 拒單會回報為交易所拒絕下單。
- timeout、network error、HTTP 5xx 或交易所暫時繁忙會回報為暫時異常。
- 使用者只看到簡短原因；`trades.error_message`、`pending_orders.error_message` 與 `system_logs.extra_data` 會保留分類、raw code/message 與上下文。
- 不自動 retry 送單，避免重複下單風險。

## Database

Schema 由 Alembic 管理，不使用 `create_all()` 建表。

主要資料表：

- `users`：Telegram 使用者、加密 API 憑證、交易設定、發單員權限。
- `trades`：交易紀錄、Bitget 訂單 ID、狀態與錯誤訊息。
- `pending_orders`：待確認訂單、callback token、order mode、掛單價、entry 區間、計算結果、狀態與過期時間。
- `notification_logs`：通知紀錄。
- `trading_pairs`：交易對與限制資料。
- `channel_groups`：受管理的 Telegram 頻道或群組，以及可選的 `message_thread_id` topic 設定。
- `system_logs`：系統操作、錯誤日誌與 `module="audit"` 的操作審計摘要。

Pending order 狀態：

- `pending`
- `processing`
- `executed`
- `failed`
- `cancelled`
- `expired`

## 安全注意事項

- `.env`、資料庫資料與 log 不應提交到 git。
- Runtime log 會摘要化，不應包含 API key、secret、passphrase 或完整交易所 response；但仍可能包含交易對、方向、數量、狀態與錯誤碼，應視為內部資料。
- `ENCRYPTION_KEY` 遺失後，既有加密 API 憑證將無法解密。
- Bot 需要能主動私訊使用者；使用者需先與 Bot 開啟對話。
- 頻道或群組轉發需要 Bot 具備相應管理權限。
- 備份檔會包含加密後的 API 憑證與交易紀錄，應與 `.env` 一樣保護。
- 還原備份時需要原本的 `ENCRYPTION_KEY`，否則還原後的 API 憑證仍無法解密使用。

## 驗證

本專案目前不做壓測或大量模擬測試。基本驗證流程：

```bash
docker compose build test
docker compose run --rm test ruff check .
docker compose run --rm test ruff format --check .
docker compose run --rm test python -m pytest
docker compose run --rm test python -m pytest --run-db
docker compose run --rm test python -m py_compile app/*.py app/repositories/*.py alembic/env.py alembic/versions/*.py tests/*.py
git diff --check
docker compose build
docker compose up -d postgres
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot python -m app.main --check-db
docker compose run --rm bot python -m app.main --cleanup-retention --dry-run
docker compose run --rm bot python -m app.main --cleanup-retention
docker compose up -d bot
docker compose up -d maintenance db-backup
docker compose ps
docker compose logs --tail 40 bot
```

接著在 Telegram 手動驗證：

- `/start`
- `/status`
- `/settings`
- `/admin`
- `/admin_health`
- 發送含備註的測試信號，確認備註顯示在 `SL` 下方且時間戳為 UTC+8
- 確認信號上出現「市价下单」與「挂单」
- 點擊兩種下單方式，確認 `pending_orders.order_mode` 與 `limit_price` 正確寫入
- 重啟 Bot 後確認尚未過期的 pending order 仍可被確認
- 若使用 forum supergroup，設定 `/set_channel_topic` 後確認信號出現在指定 topic
- 依照 [backup_restore_runbook.md](backup_restore_runbook.md) 驗證最新備份可還原
