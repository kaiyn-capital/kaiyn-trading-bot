# Production Readiness 優化紀錄

更新日期：2026-05-13

本文件用來記錄 Kaiyn Trading Bot 距離正式長期部署仍建議補強的項目，以及後續實作順序。目標不是做成大型交易平台，而是讓目前這套 Telegram + Bitget 下單 bot 可以在 VPS 上穩定長期運行，並降低真金交易時的操作風險。

## 明確不做的範圍

- 不追蹤掛單後續生命週期。
- 不實作掛單成交同步、掛單取消、掛單過期同步、止盈自動掛單。
- Bot 的責任邊界維持為：送出市價單或限價單，並記錄 Bitget 是否成功接收該筆訂單。
- 不做壓測或大量模擬測試，除非後續另行決定。

## 目前已具備的基礎

- PostgreSQL + SQLAlchemy asyncio。
- Alembic migration。
- Docker Compose 本地/部署一致環境。
- Bot、PostgreSQL、maintenance、db-backup 服務。
- Docker log rotation、Bot 檔案 log 每日輪轉。
- DB retention 與每日 PostgreSQL 備份。
- Pending order 寫入 DB，並使用 row lock 避免重複確認下單。
- 市價下單與 GTC 限價掛單。
- `/send_signal` 支援備註與 UTC+8 時間戳。
- 已完成交易所規則防呆：交易對狀態、最小下單量、最小名義價值、精度、單筆上限與止損方向檢查。
- 已完成 Bitget API 錯誤分類與使用者簡短回報。
- 已完成輕量管理員告警與 `/admin_health` 健康檢查。
- 已完成備份還原 runbook 與本地臨時 PostgreSQL 還原驗證。

## 建議實作順序

### 1. 交易安全防呆（已完成基礎版）

優先度最高。這一層直接影響是否可能送出不合理訂單。

已完成：

- 下單前檢查交易對是否存在且支援 U 本位合約。
- 檢查 Bitget 最小下單量、最小名義價值、數量精度、價格精度。
- 根據交易對規則格式化 quantity 與 limit price，不只固定 round 到 6 位。
- 檢查 Long/Short 的止損位置是否合理。
- 下單前確認 API 憑證完整；實際交易權限仍由 Bitget 送單回應判定。

本輪刻意不做：

- 不新增固定風險金額 1R 全域上限。
- 不新增止損距離百分比上下限，只阻擋 0 距離與方向錯誤。

完成標準：

- 不符合交易所規則或風控規則的訂單，在確認下單前就阻擋。
- 使用者會看到清楚錯誤訊息。
- 不送出 Bitget 明顯會拒絕的訂單。

### 2. Bitget API 錯誤處理與回報（已完成基礎版）

第二優先。目標是讓失敗可理解、可排查，避免所有錯誤都變成同一種泛用訊息。

已完成：

- 將 Bitget 錯誤分為：使用者設定問題、交易對問題、風控問題、交易所暫時問題、未知問題。
- 對 timeout、網路暫時錯誤、交易所 5xx 做明確處理。
- 對不可重試錯誤直接回報原因，不盲目重試。
- 保留原始 Bitget error code/message 到 `trades.error_message` 或 system log。
- 使用者訊息保持簡短，管理員 log 保留足夠排查資訊。

完成標準：

- 下單失敗時，使用者能知道大概原因。
- 管理員可從 log 或 DB 查到原始錯誤。
- 不會因錯誤處理不清楚而造成重複點擊、重複下單的風險。

### 3. 管理員告警與健康檢查（已完成基礎版）

第三優先。現在已有 Telegram 管理員告警與 `/admin_health`，可在部署後降低無人盯 log 的風險。

已完成：

- Bot 啟動成功或啟動失敗時通知管理員。
- DB 連線失敗通知管理員。
- Bitget API 連續失敗達門檻時通知管理員。
- maintenance cleanup 執行失敗通知管理員。
- db-backup 備份失敗通知管理員。
- `/admin_health` 指令查看 DB、Bot、備份、cleanup、Bitget API 與近期錯誤狀態。

完成標準：

- VPS 上無人盯 log 時，重大故障會主動推送到 Telegram 管理員。
- 管理員能用指令快速確認目前服務狀態。

### 4. 備份還原驗證與操作文件（已完成基礎版）

第四優先。現在有每日備份，但 production 前應確認備份真的能還原。

已完成：

- 新增 `backup_restore_runbook.md`。
- 提供將 `backups/*.sql.gz` 還原到獨立臨時 PostgreSQL DB 的指令。
- 記錄建議頻率：正式部署前至少測一次，之後每月或重大改版後測一次。
- 確認還原後 Alembic version、主要資料表、近期資料筆數可查詢。
- 此輪採文件化 runbook，不新增自動還原腳本，避免多維護一份流程。

完成標準：

- 任一備份檔可以被實際還原。
- 還原流程不依賴口頭記憶。

### 5. 核心流程測試（已完成基礎版）

第五優先。不做壓測，但要補最容易出錯的核心邏輯測試。

已建立 pytest 輕量測試框架，並改為 Docker Compose 優先執行。預設測試不打 Telegram、不打 Bitget；PostgreSQL integration 測試採 opt-in，容器內連 `postgres:5432`，使用獨立測試 schema，測完自動刪除。

已補強：

- `/send_signal` 參數解析測試，包含備註文字。
- Long/Short 掛單價格選擇測試。
- 掛單價可能立即成交時切換市價確認的測試。
- 1R 倉位計算測試。
- 交易安全防呆規則測試。
- Pending order handler confirm/cancel 分支測試。
- Pending order repository claim/cancel/expired/executed/failed PostgreSQL integration 測試。

完成標準：

- 不需要大量模擬使用者。
- 每次改交易流程前，可以快速跑過核心邏輯測試。
- 測試目標是避免回歸，不是模擬真實交易量。

### 6. 權限與操作審計

第六優先。此項不一定阻擋 beta，但會讓正式運營更容易追蹤問題。

建議補強：

- 記錄管理員操作：新增發單員、管理頻道、廣播、刪除頻道。
- 記錄發單員操作：發送信號內容、目標頻道數量。
- 記錄使用者下單操作：點擊市價/掛單、確認、取消、失敗原因。
- 提供管理員查詢近期系統事件的簡單指令。

完成標準：

- 出現爭議或錯誤時，可以從 DB/log 追到誰在什麼時間做了什麼操作。

## 建議迭代方式

每輪只做一個主題，避免把交易、安全、告警、測試混在同一輪：

1. 交易安全防呆。（已完成基礎版）
2. Bitget API 錯誤處理。（已完成基礎版）
3. 管理員告警與健康檢查。（已完成基礎版）
4. 備份還原 runbook。（已完成基礎版）
5. 核心流程測試。
6. 權限與操作審計。

每輪完成後至少跑：

```bash
docker compose build test
docker compose run --rm test python -m pytest
docker compose run --rm test python -m pytest --run-db
docker compose run --rm test python -m py_compile app/*.py alembic/env.py alembic/versions/*.py tests/*.py
git diff --check
docker compose build bot
docker compose up -d bot
docker compose logs --tail 40 bot
```

若該輪涉及 DB schema，再加跑：

```bash
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot python -m app.main --check-db
```

## Production Ready 判斷標準

完成上述項目後，這個專案可視為接近小規模正式部署標準：

- 能長期部署在 VPS 上。
- DB、log、備份不會無限制膨脹。
- 常見錯誤會主動通知管理員。
- 下單前有基本交易所規則與風控防呆。
- 下單失敗可追查原因。
- 重要操作有紀錄。
- 核心交易流程有基本回歸測試。
