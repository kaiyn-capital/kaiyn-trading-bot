# Telegram Commands

本文件整理 Kaiyn Trading Bot 的 Telegram 指令、交易信號格式、topic 轉發設定與部署後 smoke test。文件敘述使用繁體中文；表格與檢查清單中的按鈕名稱保留 Bot 目前實際顯示文字。

## User Commands

| Command | Purpose |
| ------- | ------- |
| `/start` | 開始使用 Bot 並顯示主選單 |
| `/help` | 顯示使用說明 |
| `/setapi` | 依序設定 Bitget API Key、Secret Key、Passphrase |
| `/status` | 檢查 API 連線狀態並顯示 Bitget UID |
| `/balance` | 查詢 U 本位合約帳戶 USDT 餘額 |
| `/settings` | 設定固定風險金額 1R |

## Admin Commands

| Command | Purpose |
| ------- | ------- |
| `/admin` | 管理員面板與系統統計 |
| `/admin_health` | 查看 DB、backup、cleanup、Bitget API 與近期錯誤狀態 |
| `/admin_audit [數量]` | 查看近期操作審計，預設 10 筆、最多 30 筆 |
| `/admin_users` | 查看活躍使用者列表 |
| `/add_trader Telegram_ID` | 將指定使用者設為發單員 |
| `/admin_channels` | 查看與管理頻道或群組 |
| `/add_channel @username 描述` | 新增公開頻道或群組 |
| `/add_channel -1001234567890 描述` | 新增私人群組或頻道 ID |
| `/set_channel_topic 頻道編號 topic_id [話題名稱]` | 設定交易信號轉發到指定 Telegram topic |
| `/clear_channel_topic 頻道編號` | 清除指定 topic，恢復轉發到群組本身 |
| `/admin_broadcast 訊息內容` | 向所有已管理頻道或群組廣播訊息 |
| `/send_to_channel 目標 訊息內容` | 向指定頻道或群組發送訊息 |

## Trader Commands

| Command | Purpose |
| ------- | ------- |
| `/send_signal ...` | 發送交易信號到已啟用自動轉發的頻道或群組 |

## Signal Syntax

```text
/send_signal 交易對 方向 低進場價 高進場價 止損價 止盈價1 [止盈價2] [止盈價3] [止盈價4] [備註文字]
```

範例：

```text
/send_signal BTCUSDT long 115000 115500 114200 117500 120500 123500
/send_signal ETHUSDT short 3200 3250 3300 3100 3000 2900 等待回踩後執行
```

格式規則：

- `方向` 僅支援 `long` 或 `short`。
- 止盈價從第 6 個參數開始解析。
- 第一個無法解析為數字的參數與其後內容會合併為備註。
- 備註顯示在交易信號的 `SL` 下方。
- 信號底部時間戳使用 UTC+8。

## Topic Forwarding

管理群組為 Telegram forum supergroup 時，交易信號可轉發到指定話題。

設定流程：

1. 使用 `/add_channel` 加入群組。
2. 使用 `/admin_channels` 查看頻道編號。
3. 取得 Telegram `message_thread_id`。
4. 設定指定 topic：

```text
/set_channel_topic 1 12345 交易信號
```

清除 topic：

```text
/clear_channel_topic 1
```

`[話題名稱]` 是管理員自訂備註名稱，只用於 `/admin_channels` 顯示，不要求與 Telegram 話題實際名稱一致。

指定 topic 僅套用於 `/send_signal` 交易信號自動轉發；`/admin_broadcast` 與 `/send_to_channel` 維持發到群組本身。

## Post-deploy Smoke Test

部署後使用 Telegram 驗證：

- `/start`
- `/status`
- `/settings`
- `/admin`
- `/admin_health`
- 發送含備註的測試信號，確認備註顯示在 `SL` 下方且時間戳為 UTC+8。
- 確認信號上出現「市价下单」與「挂单」。
- 點擊兩種下單方式，確認可進入 pending order 確認畫面。
- 使用 forum supergroup 時，設定 `/set_channel_topic` 後確認信號出現在指定 topic。
