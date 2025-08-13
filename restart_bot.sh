#!/bin/bash

echo "🔍 尋找相關進程..."
all_related_pids=$(ps aux | grep -E "(main\.py|telegram|bitget)" | grep -v grep | awk '{print $2}')

if [ -n "$all_related_pids" ]; then
    echo "💀 殺死進程: $all_related_pids"
    echo $all_related_pids | xargs kill -9
    sleep 1
else
    echo "✅ 沒有找到殘餘進程"
fi

echo "🚀 啟動 Bitget Telegram Bot..."
python app/main.py