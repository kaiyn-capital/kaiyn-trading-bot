# Trading Flow

本文件整理 Kaiyn Trading Bot 的交易信號、下單流程、pending order 狀態、交易安全防呆、錯誤分類與資料表摘要。按鈕名稱保留 Bot 目前實際顯示文字。

## Signal Flow

1. 管理員或發單員使用 `/send_signal` 發送交易信號。
2. Bot 將信號轉發到已啟用的頻道或群組，並附上「市价下单」與「挂单」按鈕。
3. 使用者點擊任一下單方式後，Bot 檢查 API 設定與固定風險金額 1R。
4. Bot 取得 Bitget 當前市價與 USDT-FUTURES 合約規則，計算倉位名義價值與數量。
5. Bot 檢查交易對狀態、最小下單量、最小名義價值、數量/價格精度、單筆上限與止損方向。
6. 驗證通過後，Bot 將待確認訂單寫入 `pending_orders`，並發送確認/取消按鈕。
7. 使用者確認後，Bot 使用 row lock 將 pending order 標為 `processing`，避免重複下單。
8. 送單前 Bot 重新取得市價與合約規則再驗證一次。
9. Bitget 下單完成後，Bot 更新 `trades` 與 `pending_orders` 狀態。

## Order Modes

市價下單：

- 使用當前市價計算 1R。
- 送出 market order。
- 成功後 `trades.status` 記為 `filled`。

GTC 限價掛單：

- Long 使用 entry 區間較高點。
- Short 使用 entry 區間較低點。
- 送出 GTC limit order 並同時帶止損。
- 成功後 `trades.status` 記為 `pending`。
- 掛單價格已可能立即成交時，Bot 切換到市價下單確認流程並提示原因。

## Position Sizing

```text
止損距離百分比 = abs(計算價格 - 止損價) / 計算價格
倉位名義價值 = 固定風險金額 1R / 止損距離百分比
交易數量 = 倉位名義價值 / 計算價格
```

市價下單的計算價格為當前市價；限價掛單的計算價格為掛單價。

## Exchange Rule Validation

下單預覽與確認送單前都會執行交易安全檢查：

- 交易對必須存在於 Bitget `USDT-FUTURES` 且狀態為 `normal`。
- 下單數量需符合 `minTradeNum`、`sizeMultiplier`、`volumePlace` 與單筆上限。
- 掛單價格需符合 `pricePlace` 與 `priceEndStep`。
- 下單名義價值需符合 `minTradeUSDT`。
- Long 止損必須低於計算價格。
- Short 止損必須高於計算價格。

風控邊界：

- 系統不額外設定 1R 全域上限。
- 系統不額外設定止損距離百分比上下限。
- 交易權限與帳戶風控由 Bitget 送單結果判定。

## Pending Order Status

| Status | Meaning |
| ------ | ------- |
| `pending` | 使用者已建立待確認訂單 |
| `processing` | 使用者已確認，Bot 已取得 row lock 並正在送單 |
| `executed` | Bitget 已接收訂單 |
| `failed` | 驗證或送單失敗 |
| `cancelled` | 使用者取消 |
| `expired` | pending order 已過期 |

## Error Categories

| Category | User-facing meaning |
| -------- | ------------------- |
| API 設定或權限異常 | API key、權限、簽名或 IP whitelist 問題 |
| 交易對問題 | 交易對不存在或不可交易 |
| 交易所拒絕下單 | Bitget 接收請求但拒絕訂單 |
| 暫時異常 | timeout、network error、HTTP 5xx 或交易所繁忙 |
| 未知錯誤 | 無法分類的例外 |

使用者只看到簡短原因；`trades.error_message`、`pending_orders.error_message` 與 `system_logs.extra_data` 保留分類、raw code/message 與上下文。系統不自動 retry 送單，避免重複下單風險。

## Schema Summary

Schema 由 Alembic migration 管理。

| Table | Purpose |
| ----- | ------- |
| `users` | Telegram 使用者、加密 API 憑證、交易設定、發單員權限 |
| `trades` | 交易紀錄、Bitget 訂單 ID、狀態與錯誤訊息 |
| `pending_orders` | 待確認訂單、callback token、order mode、掛單價、entry 區間、計算結果、狀態與過期時間 |
| `notification_logs` | 通知紀錄 |
| `trading_pairs` | 交易對與限制資料 |
| `channel_groups` | Telegram 頻道或群組，以及可選的 `message_thread_id` topic 設定 |
| `system_logs` | 系統操作、錯誤日誌與 `module="audit"` 的操作審計摘要 |
