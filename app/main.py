#!/usr/bin/env python3
"""
Bitget Telegram Trading Bot
主程序入口文件
"""

import asyncio
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from telegram.error import TelegramError

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.admin_alerts import send_direct_admin_alert
from app.database import (
    cleanup_retention_records,
    get_system_log_repo,
    health_check,
    init_database,
)
from app.settings import Settings
from app.telegram_formatting import html_escape


# 設置日誌
def setup_logging(settings: Settings):
    """配置日誌系統"""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    Path("logs").mkdir(exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        "logs/app.log",
        when="midnight",
        interval=1,
        backupCount=settings.retention_days,
        encoding="utf-8",
    )

    # 基本配置
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            file_handler,
        ],
        force=True,
    )

    # 設置第三方庫日誌級別
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def check_requirements(settings: Settings):
    """檢查必要的依賴和配置"""
    try:
        # 檢查配置
        settings.validate()
        init_database(settings.database_url, debug=settings.debug)

        # 檢查必要目錄
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # 檢查資料庫
        if not await health_check():
            logging.error("Database health check failed")
            await send_direct_admin_alert(
                "❌ Kaiyn Trading Bot 启动前 DB 健康检查失败。",
                alert_key="startup_db_failure",
                settings=settings,
            )
            return False

        return True

    except (OSError, SQLAlchemyError, ValueError) as e:
        logging.error(f"Requirements check failed: {e}")
        await send_direct_admin_alert(
            f"❌ Kaiyn Trading Bot 启动前系统检查失败。\n\n错误：{html_escape(e)}",
            alert_key="startup_requirements_failure",
            settings=settings,
        )
        return False


async def main():
    """主函數"""
    print("🚀 啟動 Bitget Telegram 交易機器人...")
    settings = Settings.from_env()

    # 設置日誌
    setup_logging(settings)
    logger = logging.getLogger(__name__)

    try:
        # 檢查運行要求
        if not await check_requirements(settings):
            logger.error("❌ 系統檢查失敗，無法啟動")
            return 1

        logger.info("資料庫連線檢查完成")

        # 啟動機器人
        logger.info("啟動 Telegram 機器人...")
        from app.bot import run_bot

        await run_bot(settings)

        return 0

    except KeyboardInterrupt:
        logger.info("👋 收到中斷信號，正在關閉...")
        return 0

    except (OSError, RuntimeError, SQLAlchemyError, TelegramError, ValueError) as e:
        logger.error(f"❌ 啟動失敗: {e}")
        await send_direct_admin_alert(
            f"❌ Kaiyn Trading Bot 启动失败。\n\n错误：{html_escape(e)}",
            alert_key="startup_failure",
            settings=settings,
        )
        return 1


async def run_cleanup_retention(dry_run: bool = False) -> int:
    """Run retention cleanup without requiring Telegram credentials."""
    settings = Settings.from_env()
    setup_logging(settings)
    logger = logging.getLogger(__name__)

    try:
        settings.validate_database_url()
        init_database(settings.database_url, debug=settings.debug)

        if not await health_check():
            print("❌ 資料庫連接失敗")
            await send_direct_admin_alert(
                "❌ Kaiyn Trading Bot maintenance cleanup 无法连接 DB。",
                alert_key="maintenance_db_failure",
                settings=settings,
            )
            return 1

        result = await cleanup_retention_records(
            retention_days=settings.retention_days,
            dry_run=dry_run,
        )
        action = "將清理" if dry_run else "已清理"
        print(
            f"✅ Retention cleanup {'dry run' if dry_run else 'completed'} "
            f"(retention_days={result['retention_days']}, cutoff={result['cutoff']})"
        )
        for table_name, count in result["tables"].items():
            print(f"- {table_name}: {action} {count} 筆")

        logger.info(f"Retention cleanup result: {result}")
        await get_system_log_repo().log(
            level="INFO",
            message=("Retention cleanup dry run completed" if dry_run else "Retention cleanup completed"),
            module="maintenance",
            function="run_cleanup_retention",
            extra_data=result,
        )
        return 0

    except (OSError, SQLAlchemyError, ValueError) as e:
        logger.error(f"Retention cleanup failed: {e}")
        print(f"❌ Retention cleanup failed: {e}")
        try:
            await get_system_log_repo().log(
                level="ERROR",
                message=f"Retention cleanup failed: {e}",
                module="maintenance",
                function="run_cleanup_retention",
                extra_data={"dry_run": dry_run, "error": str(e)},
            )
        except SQLAlchemyError as log_error:
            logger.error(f"Failed to persist cleanup failure log: {log_error}")
        await send_direct_admin_alert(
            f"❌ Kaiyn Trading Bot maintenance cleanup 失败。\n\n错误：{html_escape(e)}",
            alert_key="maintenance_cleanup_failed",
            settings=settings,
        )
        return 1


def generate_encryption_key():
    """生成加密金鑰的工具函數"""
    from app.encryption import KeyGenerator

    key = KeyGenerator.generate_key()
    print(f"Generated encryption key: {key}")
    print(f"Add this to your .env file: ENCRYPTION_KEY={key}")
    return key


def create_env_template():
    """創建環境變數模板"""
    from app.encryption import KeyGenerator

    template = """# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_ADMIN_IDS=your_telegram_user_id,another_admin_id

# PostgreSQL Configuration
POSTGRES_DB=kaiyn_trading_bot
POSTGRES_USER=kaiyn
POSTGRES_PASSWORD=kaiyn
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://kaiyn:kaiyn@postgres:5432/kaiyn_trading_bot

# Encryption Key (32 bytes base64 encoded)
ENCRYPTION_KEY={encryption_key}

# Bitget API Configuration
BITGET_API_URL=https://api.bitget.com

# Application Settings
DEBUG=True
LOG_LEVEL=INFO
MAX_DAILY_TRADES=10
MAX_POSITION_SIZE=1000
RETENTION_DAYS=30
MAINTENANCE_INTERVAL_SECONDS=86400
BACKUP_INTERVAL_SECONDS=86400
BACKUP_LOCAL_KEEP_COUNT=3
R2_BACKUP_ENABLED=false
R2_ACCOUNT_ID=
R2_ENDPOINT=
R2_BUCKET=kaiyn-trading-bot-backups
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BACKUP_PREFIX=kaiyn-trading-bot
BACKUP_ENCRYPTION_KEY=generate_with_make_generate_backup_key
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
"""

    key = KeyGenerator.generate_key()
    template = template.format(encryption_key=key)

    with open(".env.template", "w", encoding="utf-8") as f:
        f.write(template)

    print("✅ .env.template 文件已創建")
    print("請將其複製為 .env 並填入正確的配置值")


def init_project():
    """初始化項目"""
    print("🔧 初始化項目...")

    # 創建必要目錄
    dirs = ["logs", "data", "backups"]
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        print(f"✅ 創建目錄: {dir_name}")

    # 創建環境變數模板
    if not Path(".env").exists():
        create_env_template()

    print("🎉 項目初始化完成！")
    print("\n下一步：")
    print("1. 編輯 .env 文件，填入正確的配置")
    print("2. 運行 'docker compose run --rm bot alembic upgrade head' 套用資料庫 migration")
    print("3. 運行 'docker compose up bot' 啟動機器人")


def show_help():
    """顯示幫助信息"""
    help_text = """
🤖 Bitget Telegram 交易機器人

使用方法:
  python app/main.py                    啟動機器人
  python app/main.py --init            初始化項目
  python app/main.py --generate-key    生成加密金鑰
  python app/main.py --check-db        檢查 PostgreSQL 連線
  python app/main.py --cleanup-retention [--dry-run]
                                        清理超過保留期限的累積資料
  python app/main.py --help            顯示此幫助

配置文件:
  .env                                 環境變數配置

日誌文件:
  logs/app.log                        應用日誌
  logs/                               日誌目錄

資料庫:
  PostgreSQL                          使用 Alembic 管理 schema
  alembic upgrade head                套用資料庫 migration
  
安全提醒:
  - 請妥善保管您的 API 金鑰
  - 建議只授予交易權限，不要授予提幣權限
  - 定期備份資料庫文件
  - 使用強密碼保護服務器
    """
    print(help_text)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bitget Telegram Trading Bot")
    parser.add_argument("--init", action="store_true", help="初始化項目")
    parser.add_argument("--generate-key", action="store_true", help="生成加密金鑰")
    parser.add_argument("--check-db", action="store_true", help="檢查資料庫連接")
    parser.add_argument("--create-tables", action="store_true", help="已停用，請使用 alembic upgrade head")
    parser.add_argument("--cleanup-retention", action="store_true", help="清理超過保留期限的資料")
    parser.add_argument("--dry-run", action="store_true", help="搭配 --cleanup-retention，只顯示會清理的筆數")

    args = parser.parse_args()

    if args.init:
        init_project()
    elif args.generate_key:
        generate_encryption_key()
    elif args.check_db:
        settings = Settings.from_env()
        setup_logging(settings)
        try:
            settings.validate_database_url()
            init_database(settings.database_url, debug=settings.debug)
            if asyncio.run(health_check()):
                print("✅ 資料庫連接正常")
            else:
                print("❌ 資料庫連接失敗")
                sys.exit(1)
        except (OSError, SQLAlchemyError, ValueError) as e:
            print(f"❌ 資料庫連接失敗: {e}")
            sys.exit(1)
    elif args.create_tables:
        print("❌ --create-tables 已停用，請改用：alembic upgrade head")
        sys.exit(1)
    elif args.cleanup_retention:
        exit_code = asyncio.run(run_cleanup_retention(dry_run=args.dry_run))
        sys.exit(exit_code)
    elif len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h"]:
        show_help()
    else:
        # 運行主程序
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
