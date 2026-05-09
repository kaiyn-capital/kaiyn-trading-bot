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
- 管理員與發單員權限管理
- 頻道或群組管理與交易信號轉發
- Pending order 寫入 PostgreSQL，Bot 重啟後仍可確認尚未過期的訂單

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

## 專案結構

```text
.
├── alembic/                 # Database migrations
├── app/
│   ├── main.py              # CLI 入口、啟動流程、初始化工具
│   ├── bot.py               # Telegram Bot 指令、按鈕、交易流程
│   ├── bitget_api.py        # Bitget API client 與交易管理器
│   ├── config.py            # 環境變數設定與驗證
│   ├── database.py          # PostgreSQL async repositories
│   ├── encryption.py        # API 憑證加解密
│   └── models.py            # SQLAlchemy models
├── alembic.ini
├── compose.yml
├── Dockerfile
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
```

`DATABASE_URL` 必須使用 `postgresql+asyncpg://`。此專案不再支援 SQLite fallback。

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

查看 log：

```bash
docker compose logs -f bot
```

重啟 Bot：

```bash
./restart_bot.sh
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
- `/admin_users`：查看活躍使用者列表。
- `/admin_channels`：查看與管理頻道或群組。
- `/add_channel @username 描述`：新增公開頻道或群組。
- `/add_channel -1001234567890 描述`：新增私人群組或頻道 ID。
- `/admin_broadcast 訊息內容`：向所有已管理頻道或群組廣播訊息。
- `/send_to_channel 目標 訊息內容`：向指定頻道或群組發送訊息。
- `/add_trader Telegram_ID`：將指定使用者設為發單員。
- `/send_signal ...`：發送交易信號。

發單員：

- `/send_signal ...`：發送交易信號到已啟用自動轉發的頻道或群組。

## 交易信號格式

```text
/send_signal 交易對 方向 低進場價 高進場價 止損價 止盈價1 [止盈價2] [止盈價3] [止盈價4]
```

範例：

```text
/send_signal BTCUSDT long 115000 115500 114200 117500 120500 123500
/send_signal ETHUSDT short 3200 3250 3300 3100 3000 2900
```

## 下單流程

1. 管理員或發單員使用 `/send_signal` 發送交易信號。
2. Bot 將信號轉發到已啟用的頻道或群組，並附上下單按鈕。
3. 使用者點擊下單後，Bot 會檢查 API 設定與固定風險金額 1R。
4. Bot 取得 Bitget 當前市價，計算倉位名義價值與數量。
5. Bot 將待確認訂單寫入 `pending_orders`，並發送確認/取消按鈕。
6. 使用者確認後，Bot 使用 row lock 將 pending order 標為 `processing`，避免重複下單。
7. Bitget 下單完成後，Bot 更新 `trades` 與 `pending_orders` 狀態。

倉位計算概念：

```text
止損距離百分比 = abs(目前價格 - 止損價) / 目前價格
倉位名義價值 = 固定風險金額 1R / 止損距離百分比
交易數量 = 倉位名義價值 / 目前價格
```

## Database

Schema 由 Alembic 管理，不使用 `create_all()` 建表。

主要資料表：

- `users`：Telegram 使用者、加密 API 憑證、交易設定、發單員權限。
- `trades`：交易紀錄、Bitget 訂單 ID、狀態與錯誤訊息。
- `pending_orders`：待確認訂單、callback token、計算結果、狀態與過期時間。
- `notification_logs`：通知紀錄。
- `trading_pairs`：交易對與限制資料。
- `channel_groups`：受管理的 Telegram 頻道或群組。
- `system_logs`：系統操作與錯誤日誌。

Pending order 狀態：

- `pending`
- `processing`
- `executed`
- `failed`
- `cancelled`
- `expired`

## 安全注意事項

- `.env`、資料庫資料與 log 不應提交到 git。
- `ENCRYPTION_KEY` 遺失後，既有加密 API 憑證將無法解密。
- Bot 需要能主動私訊使用者；使用者需先與 Bot 開啟對話。
- 頻道或群組轉發需要 Bot 具備相應管理權限。

## 驗證

本輪不做壓測或大量模擬測試。基本驗證流程：

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot python -m app.main --check-db
docker compose up -d bot
```

接著在 Telegram 手動驗證：

- `/start`
- `/status`
- `/settings`
- `/admin`
- 發送測試信號並確認 `pending_orders` 有資料
- 重啟 Bot 後確認尚未過期的 pending order 仍可被確認
