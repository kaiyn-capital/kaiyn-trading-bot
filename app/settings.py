import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from dotenv import load_dotenv


def _get_value(source: Mapping[str, str], name: str, default: str | None = None) -> str | None:
    value = source.get(name)
    return default if value is None else value


def _env_bool(source: Mapping[str, str], name: str, default: bool) -> bool:
    value = source.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(source: Mapping[str, str], name: str, default: int) -> int:
    value = source.get(name)
    if value is None:
        return default
    return int(value)


def _env_float(source: Mapping[str, str], name: str, default: float) -> float:
    value = source.get(name)
    if value is None:
        return default
    return float(value)


def _env_decimal(source: Mapping[str, str], name: str, default: str) -> Decimal:
    value = source.get(name)
    return Decimal(default if value is None else value)


def _parse_admin_ids(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str | None
    admin_ids: tuple[int, ...]
    database_url: str | None
    encryption_key: str | None
    bitget_api_url: str
    debug: bool
    log_level: str
    retention_days: int
    maintenance_interval_seconds: int
    backup_interval_seconds: int
    admin_notify_startup_success: bool
    healthcheck_interval_seconds: int
    pending_order_reconcile_after_seconds: int
    pending_order_reconcile_limit: int
    user_session_ttl_seconds: int
    admin_alert_cooldown_seconds: int
    bitget_alert_failure_threshold: int
    bitget_alert_window_seconds: int
    backup_stale_hours: int
    maintenance_stale_hours: int
    signal_chart_enabled: bool
    signal_chart_granularity: str
    signal_chart_candle_limit: int
    signal_update_candle_limit: int
    signal_chart_timeout_seconds: float
    max_daily_trades: int
    max_position_size: Decimal

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> "Settings":
        if environ is None and load_env_file:
            load_dotenv()

        source = os.environ if environ is None else environ
        return cls(
            telegram_bot_token=_get_value(source, "TELEGRAM_BOT_TOKEN"),
            admin_ids=_parse_admin_ids(source.get("TELEGRAM_ADMIN_IDS")),
            database_url=_get_value(source, "DATABASE_URL"),
            encryption_key=_get_value(source, "ENCRYPTION_KEY"),
            bitget_api_url=_get_value(source, "BITGET_API_URL", "https://api.bitget.com") or "https://api.bitget.com",
            debug=_env_bool(source, "DEBUG", False),
            log_level=_get_value(source, "LOG_LEVEL", "INFO") or "INFO",
            retention_days=_env_int(source, "RETENTION_DAYS", 30),
            maintenance_interval_seconds=_env_int(source, "MAINTENANCE_INTERVAL_SECONDS", 86400),
            backup_interval_seconds=_env_int(source, "BACKUP_INTERVAL_SECONDS", 86400),
            admin_notify_startup_success=_env_bool(source, "ADMIN_NOTIFY_STARTUP_SUCCESS", True),
            healthcheck_interval_seconds=_env_int(source, "HEALTHCHECK_INTERVAL_SECONDS", 300),
            pending_order_reconcile_after_seconds=_env_int(source, "PENDING_ORDER_RECONCILE_AFTER_SECONDS", 900),
            pending_order_reconcile_limit=_env_int(source, "PENDING_ORDER_RECONCILE_LIMIT", 10),
            user_session_ttl_seconds=_env_int(source, "USER_SESSION_TTL_SECONDS", 300),
            admin_alert_cooldown_seconds=_env_int(source, "ADMIN_ALERT_COOLDOWN_SECONDS", 1800),
            bitget_alert_failure_threshold=_env_int(source, "BITGET_ALERT_FAILURE_THRESHOLD", 3),
            bitget_alert_window_seconds=_env_int(source, "BITGET_ALERT_WINDOW_SECONDS", 600),
            backup_stale_hours=_env_int(source, "BACKUP_STALE_HOURS", 36),
            maintenance_stale_hours=_env_int(source, "MAINTENANCE_STALE_HOURS", 36),
            signal_chart_enabled=_env_bool(source, "SIGNAL_CHART_ENABLED", True),
            signal_chart_granularity=_get_value(source, "SIGNAL_CHART_GRANULARITY", "1H") or "1H",
            signal_chart_candle_limit=_env_int(source, "SIGNAL_CHART_CANDLE_LIMIT", 120),
            signal_update_candle_limit=_env_int(source, "SIGNAL_UPDATE_CANDLE_LIMIT", 200),
            signal_chart_timeout_seconds=_env_float(source, "SIGNAL_CHART_TIMEOUT_SECONDS", 8.0),
            max_daily_trades=_env_int(source, "MAX_DAILY_TRADES", 10),
            max_position_size=_env_decimal(source, "MAX_POSITION_SIZE", "1000"),
        )

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def validate(self) -> bool:
        if not self.telegram_bot_token:
            raise ValueError("Missing TELEGRAM_BOT_TOKEN")

        if not self.encryption_key:
            raise ValueError("Missing ENCRYPTION_KEY")

        if not self.admin_ids:
            raise ValueError("Missing TELEGRAM_ADMIN_IDS")

        self.validate_database_url()
        return True

    def validate_database_url(self) -> bool:
        if not self.database_url:
            raise ValueError("Missing DATABASE_URL")

        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg://")

        return True
