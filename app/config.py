import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


class Config:
    # Telegram Bot
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    # 多管理員支援
    @classmethod
    def get_admin_ids(cls) -> list[int]:
        """獲取所有管理員ID列表"""
        admin_ids_str = os.getenv("TELEGRAM_ADMIN_IDS")
        if admin_ids_str:
            return [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
        return []

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """檢查用戶是否為管理員"""
        return user_id in cls.get_admin_ids()

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL")

    # Encryption
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

    # Bitget API
    BITGET_API_URL = os.getenv("BITGET_API_URL", "https://api.bitget.com")

    # Application
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
    MAINTENANCE_INTERVAL_SECONDS = int(os.getenv("MAINTENANCE_INTERVAL_SECONDS", "86400"))
    BACKUP_INTERVAL_SECONDS = int(os.getenv("BACKUP_INTERVAL_SECONDS", "86400"))
    ADMIN_NOTIFY_STARTUP_SUCCESS = _env_bool("ADMIN_NOTIFY_STARTUP_SUCCESS", True)
    HEALTHCHECK_INTERVAL_SECONDS = int(os.getenv("HEALTHCHECK_INTERVAL_SECONDS", "300"))
    PENDING_ORDER_RECONCILE_AFTER_SECONDS = int(os.getenv("PENDING_ORDER_RECONCILE_AFTER_SECONDS", "900"))
    PENDING_ORDER_RECONCILE_LIMIT = int(os.getenv("PENDING_ORDER_RECONCILE_LIMIT", "10"))
    USER_SESSION_TTL_SECONDS = int(os.getenv("USER_SESSION_TTL_SECONDS", "300"))
    ADMIN_ALERT_COOLDOWN_SECONDS = int(os.getenv("ADMIN_ALERT_COOLDOWN_SECONDS", "1800"))
    BITGET_ALERT_FAILURE_THRESHOLD = int(os.getenv("BITGET_ALERT_FAILURE_THRESHOLD", "3"))
    BITGET_ALERT_WINDOW_SECONDS = int(os.getenv("BITGET_ALERT_WINDOW_SECONDS", "600"))
    BACKUP_STALE_HOURS = int(os.getenv("BACKUP_STALE_HOURS", "36"))
    MAINTENANCE_STALE_HOURS = int(os.getenv("MAINTENANCE_STALE_HOURS", "36"))
    SIGNAL_CHART_ENABLED = _env_bool("SIGNAL_CHART_ENABLED", True)
    SIGNAL_CHART_GRANULARITY = os.getenv("SIGNAL_CHART_GRANULARITY", "1H")
    SIGNAL_CHART_CANDLE_LIMIT = int(os.getenv("SIGNAL_CHART_CANDLE_LIMIT", "120"))
    SIGNAL_UPDATE_CANDLE_LIMIT = int(os.getenv("SIGNAL_UPDATE_CANDLE_LIMIT", "200"))
    SIGNAL_CHART_TIMEOUT_SECONDS = _env_float("SIGNAL_CHART_TIMEOUT_SECONDS", 8.0)

    # Trading Limits
    MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "10"))
    MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "1000"))

    @classmethod
    def validate(cls) -> bool:
        """驗證必要的配置項"""
        # 檢查必要的環境變數
        if not os.getenv("TELEGRAM_BOT_TOKEN"):
            raise ValueError("Missing TELEGRAM_BOT_TOKEN")

        if not os.getenv("ENCRYPTION_KEY"):
            raise ValueError("Missing ENCRYPTION_KEY")

        if not os.getenv("TELEGRAM_ADMIN_IDS"):
            raise ValueError("Missing TELEGRAM_ADMIN_IDS")

        cls.validate_database_url()

        # 驗證管理員ID格式
        admin_ids = cls.get_admin_ids()
        if not admin_ids:
            raise ValueError("TELEGRAM_ADMIN_IDS contains no valid IDs")

        return True

    @classmethod
    def validate_database_url(cls) -> bool:
        """驗證資料庫連線設定"""
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("Missing DATABASE_URL")

        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg://")

        cls.DATABASE_URL = database_url
        return True
