#!/bin/bash
set -euo pipefail

echo "🔄 使用 Docker Compose 重啟 Kaiyn Trading Bot..."
echo "ℹ️ 如尚未套用 migration，請先執行：docker compose run --rm bot alembic upgrade head"

docker compose up -d postgres
docker compose restart bot || docker compose up -d bot
