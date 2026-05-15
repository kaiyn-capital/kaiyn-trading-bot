# Oracle Cloud ARM Deployment Runbook

本文件是 Kaiyn Trading Bot 在 Oracle Cloud Ampere A1 Flex ARM64 VM 上的部署操作手冊。部署方式維持 Docker Compose first，同一台 VM 內執行 `postgres`、`bot`、`maintenance`、`db-backup`。

Oracle Cloud Ampere A1 Flex 可使用 ARM64 架構與 Always Free 額度。專案使用的 Docker images 與 Python dependencies 支援 Linux ARM64，因此部署命令與 DigitalOcean VPS 流程一致。

參考官方文件：

- [Oracle Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm)
- [Oracle Ampere A1 Compute](https://docs.oracle.com/en-us/iaas/Content/Compute/References/arm.htm)
- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

## 1. 部署目標

正式部署規格：

- Provider：Oracle Cloud Infrastructure Compute
- Shape：Ampere A1 Flex
- Architecture：ARM64 / AArch64
- OS：Ubuntu 24.04 LTS ARM64
- Instance size：低流量部署可從 1 OCPU / 6GB RAM 開始
- Database：同機 PostgreSQL container
- Long-running services：`postgres`、`bot`、`maintenance`、`db-backup`
- Test service：`test` 僅部署前檢查使用，不長駐
- Domain / TLS / reverse proxy：不使用
- Public inbound port：只允許 SSH 22

安全決策：

- Bitget API 不綁定 IP whitelist。
- Bitget API 不開提現權限，只給交易所需最小權限。
- `.env`、`backups/`、Docker volume 與 PostgreSQL dump 都視為敏感資料。
- VM 上備份保留 30 天，另每週手動拉一份到本機或雲端。

## 2. 建立 Ampere A1 VM

在 Oracle Cloud 建立 instance：

1. Image 選擇 Ubuntu 24.04 LTS ARM64。
2. Shape 選擇 Ampere A1 Flex。
3. 低流量部署可從 1 OCPU / 6GB RAM 開始；需要更寬裕資源時再調整。
4. 使用 SSH key 登入，不使用 password login。
5. Boot volume 依實際資料與備份需求設定，避免無意超出免費額度。
6. VCN security list 或 NSG 只開放 TCP 22 inbound。
7. 保留預設 outbound，讓 VM 可連 Telegram、Bitget、Docker registry 與 package repository。

注意：

- Oracle Always Free A1 額度很高，但不同 region / availability domain 可能出現容量不足。
- 多台 A1 VM 的 OCPU、RAM 與 block volume 會加總使用額度。
- 本專案不需要 HTTP 80、HTTPS 443 或 PostgreSQL 5432 對外開放。

## 3. SSH 與 Firewall

使用 SSH key 登入 VM：

```bash
ssh ubuntu@<instance-public-ip>
```

建立部署使用者：

```bash
sudo adduser deploy
sudo usermod -aG sudo deploy
sudo rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

確認可以用 `deploy` 登入後，關閉 password login：

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

Oracle Cloud ingress 規則：

- Inbound：只允許 TCP 22。
- Outbound：保留預設允許 outbound。
- 不開 HTTP 80。
- 不開 HTTPS 443。
- 不開 PostgreSQL 5432。

VM 內也可加 UFW 作為輔助：

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status verbose
```

注意：Docker 會管理 iptables，UFW 不作為唯一防線。正式環境主要依賴 Oracle Cloud VCN security list 或 NSG 阻擋外部連線，同時 production `.env` 將 PostgreSQL host port 綁定在 `127.0.0.1`。

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
docker run --rm hello-world
uname -m
```

`uname -m` 應顯示 `aarch64`。Docker 會自動拉取支援 ARM64 的 image manifest。

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
ADMIN_NOTIFY_STARTUP_SUCCESS=True
HEALTHCHECK_INTERVAL_SECONDS=300
ADMIN_ALERT_COOLDOWN_SECONDS=1800
BITGET_ALERT_FAILURE_THRESHOLD=3
BITGET_ALERT_WINDOW_SECONDS=600
BACKUP_STALE_HOURS=36
MAINTENANCE_STALE_HOURS=36
```

產生 `ENCRYPTION_KEY`：

```bash
make build
make generate-key
```

把輸出的 key 填入 `.env`。`ENCRYPTION_KEY` 遺失後，DB 內已加密的 API credential 無法解密，所以它必須跟 PostgreSQL 備份分開保存。

## 7. 首次部署

快速流程：

```bash
make deploy
make ps
make logs
```

等效 Docker Compose 展開流程：

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot python -m app.main --check-db
docker compose up -d bot maintenance db-backup
docker compose ps
docker compose logs --tail 80 bot
```

## 8. 部署前檢查

正式上線前可在 VM 上跑一次 Docker-first 檢查：

```bash
make verify
```

等效 Docker Compose 展開流程：

```bash
docker compose build test
docker compose up -d postgres
docker compose run --rm test uv lock --check
docker compose run --rm test ruff check .
docker compose run --rm test ruff format --check .
docker compose run --rm test python -m pytest --run-db
docker compose run --rm test python -m py_compile app/*.py app/repositories/*.py alembic/env.py alembic/versions/*.py tests/*.py
git diff --check
```

## 9. 日常更新部署

進入部署目錄：

```bash
cd /opt/kaiyn-trading-bot
```

查看服務與工作樹狀態：

```bash
git status --short
make ps
```

更新程式並部署：

```bash
git pull --ff-only
make deploy
```

最後在 Telegram 執行 `/admin_health` 與基本 smoke test。

## 10. Coolify CD

Oracle Cloud ARM 可以使用同一套 GHCR image pipeline 與 Coolify webhook deployment。Release workflow 會建立 `linux/amd64` 與 `linux/arm64` multi-arch image；ARM host 會自動拉取 `linux/arm64` image。

GitHub `production` environment 需要設定：

```text
COOLIFY_TOKEN
COOLIFY_API_BASE_URL
COOLIFY_APPLICATION_UUID
COOLIFY_WEBHOOK
```

Coolify application 使用：

```text
compose.coolify.yml
```

Coolify pre-deployment command：

```bash
alembic upgrade head
```

pre-deployment command container 指定 `bot`。完整 Coolify 設定見 [coolify_runbook.md](coolify_runbook.md)。

SSH + image-based manual deployment 保留為 fallback：

```bash
BOT_IMAGE=ghcr.io/kylekkkk61/kaiyn-trading-bot@sha256:<digest> make deploy-image
```

`compose.prod.yml` 使用 Docker Compose `!reset` 移除 build 設定，fallback VM Docker Compose plugin 需支援 Compose `2.24.4+`。

## 11. 備份與還原

備份由 `db-backup` service 每日產生 gzip SQL dump：

```bash
ls -lh backups/
cat backups/backup_status.json
```

還原驗證流程見 [backup_restore_runbook.md](backup_restore_runbook.md)。Oracle Cloud boot volume snapshot 可作為 VM 層級災難恢復，但不能取代 PostgreSQL SQL 備份。

## 12. ARM64 檢查

確認 host 架構：

```bash
uname -m
docker version --format '{{.Server.Arch}}'
```

預期結果：

- `uname -m`：`aarch64`
- Docker server architecture：`arm64`

本專案不設定 `platform: linux/amd64`。Docker 會依 ARM64 host 自動拉取 ARM64 image。
