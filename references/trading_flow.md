# Trading Flow

本文件整理 Kaiyn Trading Bot 的交易信號、下單流程、pending order 狀態、交易安全防呆、錯誤分類與資料表摘要。按鈕名稱保留 Bot 目前實際顯示文字。

## Signal Flow

1. 管理員或發單員使用 `/send_signal` 建立交易信號。
2. Bot 產生永久 `交易id`，建立 `signal_records(status="preview_pending")`，並把 `交易id` 放入預覽文字。
3. Bot 會嘗試從 Bitget 取得 K 線並產生黑底風險報酬圖，然後在私人聊天回傳轉發預覽與「确认转发 / 取消」按鈕；附圖失敗時會退回純文字預覽。
4. 發單者需在 session TTL 內確認預覽；取消或被新的預覽覆蓋時，不會轉發到群組，紀錄會標記為 `cancelled` 或 `replaced`。
5. 發單者確認後，Bot 將信號轉發到已啟用的頻道或群組，並附上「市价下单」與「挂单」按鈕。
6. 每個成功轉發的群組/topic 會保存 Telegram `message_id` 到 `signal_channel_messages`，供 `/update_chart` 回覆原始發單信息。
7. 使用者點擊任一下單方式後，Bot 檢查 API 設定與固定風險金額 1R。
8. Bot 取得 Bitget 當前市價與 USDT-FUTURES 合約規則，計算倉位名義價值與數量。
9. Bot 檢查本地 hard risk caps、交易對狀態、最小下單量、最小名義價值、數量/價格精度、單筆上限與止損方向。
10. 驗證通過後，Bot 將待確認訂單寫入 `pending_orders`，並發送確認/取消按鈕。
11. 使用者確認後，Bot 使用 row lock 將 pending order 標為 `processing`，避免重複下單。
12. 送單前 Bot 重新取得市價與合約規則，並再次檢查本地 hard risk caps。
13. Bitget 下單完成後，Bot 更新 `trades` 與 `pending_orders` 狀態。
14. 若 pending order 長時間停在 `processing`，health monitor 只用 `client_order_id` 查 Bitget 補本地狀態；系統不自動重送。

## Chart Update Flow

1. 原發單者或管理員使用 `/update_chart 交易id [備註文字]`。
2. Bot 讀取 `signal_records`，驗證交易 ID 存在、原信號狀態為 `sent`，且操作者是原發單者或管理員。
3. Bot 讀取該信號原始成功轉發過的 `signal_channel_messages`；不會發到後來新增的群組。
4. Bot 重新取得目前 K 線並生成更新圖表，將原始 entry、SL、TP 與風險報酬框延伸到最新位置。
5. Bot 在私人聊天回傳更新圖表預覽與「确认转发 / 取消」按鈕；確認前不會發到群組。
6. 確認後 Bot 逐一發到原始群組/topic，優先用 Telegram `reply_to_message_id` 回覆原發單訊息。
7. 若回覆失敗，Bot 會在同一群組/topic 普通發送更新圖表；若圖片發送本身失敗，該目標計為失敗。
8. 若 K 線資料不足以覆蓋原始發單時間，Bot 不產生近似圖並提示使用者。

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

## Signal Chart

- 附圖功能由 `SIGNAL_CHART_ENABLED` 控制，預設開啟。
- 發單信號圖 K 線預設使用 Bitget `USDT-FUTURES` market candle，週期 `SIGNAL_CHART_GRANULARITY=1H`，數量 `SIGNAL_CHART_CANDLE_LIMIT=120`。
- `/update_chart` 圖表 K 線數量由 `SIGNAL_UPDATE_CANDLE_LIMIT` 控制，預設 200。
- 圖上的 entry 使用下單邏輯中的較差價格：Long 使用 entry 區間較高點，Short 使用 entry 區間較低點。
- 多個 TP 時，主風險報酬框使用最遠 TP，其餘 TP 以輔助線顯示。
- 圖表輸出使用黑底與簡化時間軸，只顯示少量短日期標籤以避免 Telegram 預覽產生過多底部留白。
- 信號圖表會先出現在私人聊天預覽，確認轉發後同一份圖表會發到已啟用自動轉發的頻道或群組。
- `/update_chart` 圖表會以原始發單時間作為風險報酬框起點，並延伸到目前最新 K 線；暫不依浮盈/浮虧改變框顏色。

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

- `users.max_position_size = NULL` 表示沒有使用者層覆寫，所有新舊使用者預設使用全域 `MAX_POSITION_SIZE`。
- 若 `users.max_position_size` 是正數，有效最大倉位名義價值取全域 `MAX_POSITION_SIZE` 與使用者 `max_position_size` 的較嚴格值；`0` 或負數視為沒有覆寫。
- 有效每日交易次數取全域 `MAX_DAILY_TRADES` 與使用者 `daily_trade_limit` 的較嚴格值。
- 每日交易次數以 UTC+8 日切計算，只計入非 `failed` 的 trade。
- 下單預覽與確認送單前都會檢查 hard risk caps；確認送單建立 trade 時會在 DB transaction 內再次檢查每日上限，避免同一使用者併發突破限制。
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

## Processing Reconciliation

- Health monitor 只掃描 `pending_orders.status="processing"` 且 `updated_at` 超過 `PENDING_ORDER_RECONCILE_AFTER_SECONDS` 的訂單，預設 15 分鐘。
- 查單使用 `build_client_order_id(pending_order.token)` 重建 Bitget `clientOid`，先查 `/api/v2/mix/order/detail`，明確查不到才查 `/api/v2/mix/order/orders-history`。
- 查到 `live` 或 `partially_filled` 時，`trades.status` 維持 `pending`，`pending_orders.status` 標為 `executed`。
- 查到 `filled` 時，`trades.status` 標為 `filled`，`pending_orders.status` 標為 `executed`。
- 查到 `canceled/cancelled`，或 detail/history 都查不到訂單時，`pending_orders.status` 標為 `failed`，並私訊使用者回到原交易信號重新按一次下單。
- Timeout、network error、API 權限錯誤或未知 Bitget status 不會自動標 failed；系統保留 `processing`、寫入 log 並通知管理員。

## Schema Summary

Schema 由 Alembic migration 管理。

| Table | Purpose |
| ----- | ------- |
| `users` | Telegram 使用者、加密 API 憑證、交易設定、發單員權限 |
| `trades` | 交易紀錄、Bitget 訂單 ID、狀態與錯誤訊息 |
| `pending_orders` | 待確認訂單、callback token、order mode、掛單價、entry 區間、計算結果、狀態與過期時間 |
| `signal_records` | 永久交易信號 ID、原發單者、信號參數、原始文字與 lifecycle 狀態 |
| `signal_channel_messages` | 每筆信號成功轉發到的群組/topic 與 Telegram message ID |
| `notification_logs` | 通知紀錄 |
| `trading_pairs` | 交易對與限制資料 |
| `channel_groups` | Telegram 頻道或群組，以及可選的 `message_thread_id` topic 設定 |
| `system_logs` | 系統操作、錯誤日誌與 `module="audit"` 的操作審計摘要 |
