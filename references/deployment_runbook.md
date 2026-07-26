# DigitalOcean VPS Deployment Runbook

本文件是 Kaiyn Trading Bot 的正式部署操作手冊。部署主線固定為 DigitalOcean Droplet + Ubuntu 24.04 LTS + Docker Compose，同一台 VPS 內執行 `postgres`、`bot`、`maintenance`、`db-backup`。

Production CD 使用 GitHub Actions 發布 GHCR image，並經 `production` environment approval 後透過 SSH 在 VPS 執行 image-based Docker Compose deployment。Coolify 設定細節集中在 [coolify_runbook.md](coolify_runbook.md)，作為可選 deployment variant 保留。

參考官方文件：

- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [DigitalOcean recommended Droplet setup](https://docs.digitalocean.com/products/droplets/getting-started/recommended-droplet-setup/)
- [DigitalOcean Cloud Firewalls](https://docs.digitalocean.com/products/networking/firewalls/how-to/configure-rules/)

## 1. 部署目標

正式部署規格：

- Provider：DigitalOcean Droplet
- OS：Ubuntu 24.04 LTS
- Instance size：依實際使用量選擇；小型 production target 可從 1 vCPU / 2GB RAM 級別開始
- Database：同機 PostgreSQL container
- Long-running services：`postgres`、`bot`、`maintenance`、`db-backup`
- Test service：`test` 僅部署前檢查使用，不長駐
- Domain / TLS / reverse proxy：不使用
- Public inbound port：只允許 SSH 22

安全決策：

- Bitget API 不綁定 IP whitelist。
- Bitget API 不開提現權限，只給交易所需最小權限。
- `.env`、`backups/`、Docker volume 與 PostgreSQL dump 都視為敏感資料。
- VPS 上備份保留 30 天，另每週手動拉一份到本機或雲端。

## 2. 建立 Droplet

在 DigitalOcean 建立 Droplet：

1. 選擇 Ubuntu 24.04 LTS。
2. 選擇靠近 Telegram 使用者與維護者的 region。
3. 選擇符合使用量的小型 production instance；低流量部署可從 1 vCPU / 2GB RAM 級別開始。
4. 使用 SSH key 登入，不使用 password login。
5. 開啟 DigitalOcean Monitoring。
6. 開啟 Droplet backups，作為 VPS 層級災難恢復；它不能取代本專案的 PostgreSQL SQL 備份。
7. 建立 tag，格式範例為 `kaiyn-trading-bot-prod`，Cloud Firewall 可套用到同 tag Droplet。

使用 DigitalOcean user data 建立 sudo user 時，依官方 recommended setup 建立非 root 使用者。先用 root 登入時，首次登入後建立部署使用者。

## 3. SSH 與 Firewall

使用 SSH key 登入 VPS：

```bash
ssh root@<droplet-ip>
```

建立部署使用者：

```bash
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

確認可以用 `deploy` 登入後，再關閉 password login：

```bash
sudoedit /etc/ssh/sshd_config
```

確認或加入：

```text
PasswordAuthentication no
PermitRootLogin prohibit-password
```

驗證 sshd config 並重新載入：

```bash
sudo sshd -t
sudo systemctl reload ssh
```

DigitalOcean Cloud Firewall 規則：

- Inbound：只允許 TCP 22。
- Outbound：保留預設允許 outbound。
- 不開 HTTP 80。
- 不開 HTTPS 443。
- 不開 PostgreSQL 5432。

VPS 內也可加 UFW 作為輔助：

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status verbose
```

注意：Docker 會管理 iptables，UFW 不作為唯一防線。正式環境主要依賴 DigitalOcean Cloud Firewall 阻擋外部連線，同時 production `.env` 將 PostgreSQL host port 綁定在 `127.0.0.1`。

## 4. 安裝 Docker Engine

切到部署使用者：

```bash
su - deploy
```

依 Docker 官方 Ubuntu apt repository 安裝 Docker Engine 與 Compose plugin：

```bash
sudo apt update
sudo apt install ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

允許 `deploy` 使用 Docker：

```bash
sudo usermod -aG docker deploy
```

登出並重新 SSH 登入，確認 Docker 與 Compose 可用：

```bash
docker --version
docker compose version
docker run hello-world
```

## 5. 取得專案

建立部署目錄：

```bash
sudo mkdir -p /opt/kaiyn-trading-bot
sudo chown -R deploy:deploy /opt/kaiyn-trading-bot
```

clone repo：

```bash
git clone <your-repo-url> /opt/kaiyn-trading-bot
cd /opt/kaiyn-trading-bot
```

repo 已存在時，更新使用：

```bash
git pull --ff-only
```

## 6. 建立 Production `.env`

複製 template：

```bash
cp .env.template .env
chmod 600 .env
```

編輯 `.env`：

```bash
nano .env
```

正式環境至少要確認：

```env
TELEGRAM_BOT_TOKEN=<production_bot_token>
TELEGRAM_ADMIN_IDS=<admin_telegram_id_1>,<admin_telegram_id_2>

POSTGRES_DB=kaiyn_trading_bot
POSTGRES_USER=kaiyn
POSTGRES_PASSWORD=<strong_random_password>
POSTGRES_PORT=127.0.0.1:5432
DATABASE_URL=postgresql+asyncpg://kaiyn:<strong_random_password>@postgres:5432/kaiyn_trading_bot

ENCRYPTION_KEY=<fernet_key>
BITGET_API_URL=https://api.bitget.com
DEBUG=False
LOG_LEVEL=INFO
RETENTION_DAYS=30
MAINTENANCE_INTERVAL_SECONDS=86400
BACKUP_INTERVAL_SECONDS=86400
BACKUP_LOCAL_KEEP_COUNT=3
R2_BACKUP_ENABLED=true
R2_ACCOUNT_ID=<cloudflare_account_id>
R2_ENDPOINT=
R2_BUCKET=kaiyn-trading-bot-backups
R2_ACCESS_KEY_ID=<r2_access_key_id>
R2_SECRET_ACCESS_KEY=<r2_secret_access_key>
R2_BACKUP_PREFIX=kaiyn-trading-bot
BACKUP_ENCRYPTION_KEY=<backup_fernet_key>
ADMIN_NOTIFY_STARTUP_SUCCESS=True
HEALTHCHECK_INTERVAL_SECONDS=300
ADMIN_ALERT_COOLDOWN_SECONDS=1800
BITGET_ALERT_FAILURE_THRESHOLD=3
BITGET_ALERT_WINDOW_SECONDS=600
BACKUP_STALE_HOURS=36
MAINTENANCE_STALE_HOURS=36
SIGNAL_CHART_ENABLED=true
SIGNAL_CHART_GRANULARITY=1H
SIGNAL_CHART_CANDLE_LIMIT=120
SIGNAL_CHART_TIMEOUT_SECONDS=8
```

產生 `ENCRYPTION_KEY`：

```bash
docker compose build bot
docker compose run --rm bot python -m app.main --generate-key
```

把輸出的 key 填入 `.env`。`ENCRYPTION_KEY` 遺失後，DB 內已加密的 API credential 無法解密，所以它必須跟 PostgreSQL 備份分開保存。

產生 `BACKUP_ENCRYPTION_KEY`：

```bash
make generate-backup-key
```

把輸出的 key 填入 `.env`。`BACKUP_ENCRYPTION_KEY` 用於 R2 備份上傳前加密，遺失後 R2 上的 SQL dump 不能解密。它可以和 `ENCRYPTION_KEY` 不同，且應同樣離線保存。

注意：

- `POSTGRES_PASSWORD` 必須同步出現在 `DATABASE_URL`。
- Production Compose 固定把 PostgreSQL 綁在 host 的 `127.0.0.1:5432`，不對公網介面監聽；`POSTGRES_PORT` 只供基礎 Compose 的本機開發設定使用。
- Production Compose 會要求明確設定 `POSTGRES_PASSWORD` 與 `DATABASE_URL`；修改環境變數不會自動旋轉既有 PostgreSQL role 密碼。
- R2 token 建議使用 Object Read & Write，並限制到備份 bucket。
- Telegram token、admin IDs、DB password、R2 secret、encryption key 都不要提交到 git。

## 7. 首次部署

快速流程：

```bash
make deploy
make ps
make logs
```

等效 Docker Compose 展開流程：

建置 image：

```bash
docker compose build
```

啟動 PostgreSQL：

```bash
docker compose up -d postgres
```

執行 migration：

```bash
docker compose run --rm bot alembic upgrade head
```

檢查 DB：

```bash
docker compose run --rm bot python -m app.main --check-db
```

啟動正式服務：

```bash
docker compose up -d bot maintenance db-backup
```

檢查服務：

```bash
docker compose ps
docker compose logs --tail 80 bot
docker compose logs --tail 80 maintenance
docker compose logs --tail 80 db-backup
```

## 8. 部署前檢查

正式上線前可在 VPS 上跑一次 Docker-first 檢查：

```bash
make verify
```

`make verify` 主要執行項目：

```bash
make build-test
make lock-check
make migrate-test
make alembic-check
make lint
make format-check
make mypy
make test-db
make py-compile
make diff-check
```

`test` service 只在 `docker compose run` 時啟動，不會因一般 `docker compose up -d` 長駐。

## 9. Telegram Smoke Test

首次部署後，用 Telegram 手動檢查：

- `/start`
- `/help`
- `/status`
- `/settings`
- `/admin`
- `/admin_health`
- `/admin_audit`
- `/send_signal BTCUSDT short entry[80200 81000] sl[81700] tp[77777 75000] 等待回踩後執行`
- 確認信號已轉發到指定群組或 topic。
- 點「市价下单」與「挂单」，至少確認可進入 pending order 確認畫面。

使用真 API 測試送單時，使用低風險 1R，並確認 Bitget API 沒有提現權限。

## 10. 日常更新部署

進入部署目錄：

```bash
cd /opt/kaiyn-trading-bot
```

查看服務與工作樹狀態：

```bash
git status --short
docker compose ps
```

更新程式：

```bash
git pull --ff-only
```

執行部署：

```bash
make deploy
```

等效 Docker Compose 展開流程：

建置 image：

```bash
docker compose build
```

確保 PostgreSQL 正常：

```bash
docker compose up -d postgres
```

套用 migration：

```bash
docker compose run --rm bot alembic upgrade head
```

檢查 DB：

```bash
docker compose run --rm bot python -m app.main --check-db
```

重啟正式服務：

```bash
docker compose up -d bot maintenance db-backup
```

檢查結果：

```bash
make ps
make logs
```

最後在 Telegram 執行 `/admin_health` 與基本 smoke test。

## 11. GitHub Actions SSH CD

Production CD 使用 `.github/workflows/release.yml` 與 VPS SSH：

```text
CI passed
-> build linux/amd64 + linux/arm64 image
-> push GHCR
-> wait for production environment approval
-> SSH to VPS
-> deploy image digest with make deploy-image
```

GitHub `production` environment 需要設定下列 secrets：

```text
PRODUCTION_SSH_HOST
PRODUCTION_SSH_PORT
PRODUCTION_SSH_USER
PRODUCTION_SSH_KEY
PRODUCTION_SSH_KNOWN_HOSTS
PRODUCTION_APP_DIR
```

VPS 的 production worktree remote 也應指向目前 GitHub repository。若專案轉移到 organization，請在 VPS 上執行一次：

```bash
cd $PRODUCTION_APP_DIR
git remote set-url origin https://github.com/kaiyn-capital/kaiyn-trading-bot.git
```

若 GHCR package 是 private，VPS Docker client 必須能讀取新的 organization package。請用具備 `read:packages` 權限的 GitHub token，在 VPS 上以 production deploy user 執行一次：

```bash
printf '%s' '<github_pat_with_read_packages>' | docker login ghcr.io -u <github-username-or-machine-user> --password-stdin
```

若不想在 VPS 保存 GHCR login，也可以把 `ghcr.io/kaiyn-capital/kaiyn-trading-bot` package 設為 public。

遠端部署流程：

```text
cd $PRODUCTION_APP_DIR
git status must be clean
git remote set-url origin https://github.com/kaiyn-capital/kaiyn-trading-bot.git
git fetch origin main
git checkout main
git merge --ff-only $DEPLOY_SHA
BOT_IMAGE=ghcr.io/kaiyn-capital/kaiyn-trading-bot@sha256:<digest> make deploy-image
docker compose ps
docker compose logs --tail 80 bot
```

`make deploy-image` 使用 `compose.yml` 與 `compose.prod.yml`，部署順序為：

```text
start PostgreSQL with production configuration
-> pull GHCR image by digest
-> run alembic upgrade head with the deployment image
-> run DB health check with the deployment image
-> start bot, maintenance, db-backup
-> record the deployed image digest in .bot_image
```

`.bot_image` 只保存目前部署的 GHCR image digest，不是 secret，且不提交到 git。後續在 VPS 手動執行 `make backup-now`、`make r2-download-latest`、`make restore-latest`、`make disaster-restore` 時，Makefile 會自動用 `.bot_image` 切到 `compose.prod.yml`，避免在 VPS 上 build local image。

手動執行同一套 image-based deployment：

```bash
BOT_IMAGE=ghcr.io/kaiyn-capital/kaiyn-trading-bot@sha256:<digest> make deploy-image
```

`compose.prod.yml` 使用 Docker Compose `!reset` 移除 build 設定，VPS Docker Compose plugin 需支援 Compose `2.24.4+`。Coolify 方案保留為可選部署變體，完整設定見 [coolify_runbook.md](coolify_runbook.md)。

## 12. Rollback

確認當前 commit：

```bash
git log --oneline -n 10
```

程式版本回退時，切到上一個已知可用 commit 或 tag：

```bash
git switch --detach <known-good-commit-or-tag>
docker compose build
docker compose up -d bot maintenance db-backup
docker compose logs --tail 80 bot
```

使用 GHCR image-based deployment 時，可改用上一個已知可用 image digest：

```bash
BOT_IMAGE=ghcr.io/kaiyn-capital/kaiyn-trading-bot@sha256:<known-good-digest> make deploy-image
```

注意：

- Alembic migration 已套用後，不在 production 自動 downgrade。
- 新 migration 導致資料庫不可用時，先停止 bot，再依照 [backup_restore_runbook.md](backup_restore_runbook.md) 選擇備份還原。
- 正式部署前使用 git tag 標記可回退版本，格式範例為 `prod-2026-05-14`。

## 13. 備份與還原

查看備份狀態：

```bash
cat backups/backup_status.json
cat backups/backup_manifest.json
ls -lh backups
docker compose logs --tail 80 db-backup
```

高風險操作前立即打一份備份：

```bash
make backup-now
```

新產生的本機備份、checksum 與狀態檔使用 owner-only permissions；既有備份不會由部署流程自動改權限或刪除。

若 R2 已啟用，確認遠端上傳狀態：

```bash
cat backups/r2_backup_status.json
```

新 VPS 從 R2 還原最新備份：

```bash
make disaster-restore
```

每週或重大變更後，也可以手動拉一份最新本機備份與 checksum 到本機：

```bash
scp deploy@<droplet-ip>:/opt/kaiyn-trading-bot/backups/kaiyn_trading_bot_*.sql.gz ./kaiyn-backups/
scp deploy@<droplet-ip>:/opt/kaiyn-trading-bot/backups/kaiyn_trading_bot_*.sql.gz.sha256 ./kaiyn-backups/
```

還原最新本機備份：

```bash
make restore-latest
```

若目標 DB 非空且確定要覆蓋：

```bash
CONFIRM_RESTORE=YES make restore-latest
```

完整流程請以 [backup_restore_runbook.md](backup_restore_runbook.md) 為準。

## 14. 常用操作

查看服務：

```bash
docker compose ps
```

查看 bot log：

```bash
docker compose logs -f bot
```

重啟 bot：

```bash
docker compose restart bot
```

停止 bot，但保留 DB 與備份服務：

```bash
docker compose stop bot
```

停止全部服務：

```bash
docker compose down
```

手動 dry-run 清理：

```bash
docker compose run --rm bot python -m app.main --cleanup-retention --dry-run
```

手動執行清理：

```bash
docker compose run --rm bot python -m app.main --cleanup-retention
```

## 15. 常見故障處理

### Bot 沒有啟動

```bash
docker compose ps
docker compose logs --tail 120 bot
```

常見原因：

- `.env` 缺 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_ADMIN_IDS` 或 `ENCRYPTION_KEY`。
- `DATABASE_URL` 密碼與 `POSTGRES_PASSWORD` 不一致。
- migration 尚未執行。
- Telegram bot token 錯誤。

### DB 連線失敗

```bash
docker compose ps
docker compose logs --tail 120 postgres
docker compose run --rm bot python -m app.main --check-db
```

常見原因：

- `postgres` service 尚未 healthy。
- `.env` 的 `POSTGRES_PASSWORD` 與 `DATABASE_URL` 不一致。
- 手動改過 `POSTGRES_DB` 或 `POSTGRES_USER`，但既有 volume 仍是舊資料庫初始化狀態。

### Migration 失敗

```bash
docker compose run --rm bot alembic current
docker compose run --rm bot alembic heads
docker compose run --rm bot alembic upgrade head
```

migration 已部分套用且無法修復時，不要手動改正式 DB。先備份現況，再依照 [backup_restore_runbook.md](backup_restore_runbook.md) 評估是否還原到上一份備份。

### 備份沒有更新

```bash
docker compose ps
docker compose logs --tail 120 db-backup
cat backups/backup_status.json
```

常見原因：

- `db-backup` service 沒啟動。
- PostgreSQL 密碼不一致。
- VPS 磁碟空間不足。

### 磁碟空間不足

```bash
df -h
du -sh logs backups
docker system df
```

本專案已設定 Docker log rotation、Bot log rotation、DB retention 與 backup retention。磁碟仍不足時，確認是否存在舊 image 或未使用 container：

```bash
docker image prune
docker container prune
```

不要刪除 Docker volume，除非已確認要清空 PostgreSQL 資料。

## 16. Production Checklist

上線前確認：

- Droplet 使用 SSH key 登入。
- Password login 已關閉。
- DigitalOcean Cloud Firewall 只允許 TCP 22 inbound。
- `.env` 權限為 `600`。
- `POSTGRES_PASSWORD` 是正式強密碼，且與 `DATABASE_URL` 一致。
- `POSTGRES_PORT=127.0.0.1:5432`。
- `ENCRYPTION_KEY` 已離線保存。
- Bitget API 不含提現權限。
- 已執行 `alembic upgrade head`。
- `docker compose run --rm bot python -m app.main --check-db` 成功。
- `docker compose up -d bot maintenance db-backup` 已啟動。
- `/admin_health` 正常。
- `backups/backup_status.json` 有成功紀錄。
- 已依照 [backup_restore_runbook.md](backup_restore_runbook.md) 做過至少一次還原驗證。
