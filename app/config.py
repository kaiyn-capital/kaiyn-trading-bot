from typing import Any, ClassVar

from .settings import Settings

_CONFIG_ATTRIBUTE_MAP = {
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "DATABASE_URL": "database_url",
    "ENCRYPTION_KEY": "encryption_key",
    "BITGET_API_URL": "bitget_api_url",
    "DEBUG": "debug",
    "LOG_LEVEL": "log_level",
    "RETENTION_DAYS": "retention_days",
    "MAINTENANCE_INTERVAL_SECONDS": "maintenance_interval_seconds",
    "BACKUP_INTERVAL_SECONDS": "backup_interval_seconds",
    "ADMIN_NOTIFY_STARTUP_SUCCESS": "admin_notify_startup_success",
    "HEALTHCHECK_INTERVAL_SECONDS": "healthcheck_interval_seconds",
    "PENDING_ORDER_RECONCILE_AFTER_SECONDS": "pending_order_reconcile_after_seconds",
    "PENDING_ORDER_RECONCILE_LIMIT": "pending_order_reconcile_limit",
    "USER_SESSION_TTL_SECONDS": "user_session_ttl_seconds",
    "ADMIN_ALERT_COOLDOWN_SECONDS": "admin_alert_cooldown_seconds",
    "BITGET_ALERT_FAILURE_THRESHOLD": "bitget_alert_failure_threshold",
    "BITGET_ALERT_WINDOW_SECONDS": "bitget_alert_window_seconds",
    "BACKUP_STALE_HOURS": "backup_stale_hours",
    "MAINTENANCE_STALE_HOURS": "maintenance_stale_hours",
    "SIGNAL_CHART_ENABLED": "signal_chart_enabled",
    "SIGNAL_CHART_GRANULARITY": "signal_chart_granularity",
    "SIGNAL_CHART_CANDLE_LIMIT": "signal_chart_candle_limit",
    "SIGNAL_CHART_TIMEOUT_SECONDS": "signal_chart_timeout_seconds",
    "MAX_DAILY_TRADES": "max_daily_trades",
    "MAX_POSITION_SIZE": "max_position_size",
}


class _ConfigMeta(type):
    def __getattr__(cls, name: str) -> Any:
        settings_attribute = _CONFIG_ATTRIBUTE_MAP.get(name)
        if settings_attribute is None:
            raise AttributeError(name)
        return getattr(cls.settings(), settings_attribute)


class Config(metaclass=_ConfigMeta):
    """Compatibility shim. New runtime code should accept Settings explicitly."""

    _settings: ClassVar[Settings | None] = None

    @classmethod
    def settings(cls) -> Settings:
        if cls._settings is None:
            cls._settings = Settings.from_env()
        return cls._settings

    @classmethod
    def reload(cls, settings: Settings | None = None) -> Settings:
        cls._settings = settings or Settings.from_env()
        return cls._settings

    @classmethod
    def get_admin_ids(cls) -> list[int]:
        return list(cls.settings().admin_ids)

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        return cls.settings().is_admin(user_id)

    @classmethod
    def validate(cls) -> bool:
        return cls.settings().validate()

    @classmethod
    def validate_database_url(cls) -> bool:
        return cls.settings().validate_database_url()
