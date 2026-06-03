from decimal import Decimal

from app.settings import Settings


def make_settings(**overrides) -> Settings:
    data = {
        "telegram_bot_token": "test-token",
        "admin_ids": (111,),
        "database_url": "postgresql+asyncpg://user:pass@postgres:5432/test",
        "encryption_key": "test-encryption-key",
        "bitget_api_url": "https://api.bitget.com",
        "debug": False,
        "log_level": "INFO",
        "retention_days": 30,
        "maintenance_interval_seconds": 86400,
        "backup_interval_seconds": 86400,
        "admin_notify_startup_success": True,
        "healthcheck_interval_seconds": 300,
        "pending_order_reconcile_after_seconds": 900,
        "pending_order_reconcile_limit": 10,
        "user_session_ttl_seconds": 300,
        "admin_alert_cooldown_seconds": 1800,
        "bitget_alert_failure_threshold": 3,
        "bitget_alert_window_seconds": 600,
        "backup_stale_hours": 36,
        "maintenance_stale_hours": 36,
        "signal_chart_enabled": True,
        "signal_chart_granularity": "1H",
        "signal_chart_candle_limit": 120,
        "signal_chart_timeout_seconds": 8.0,
        "max_daily_trades": 10,
        "max_position_size": Decimal("1000"),
    }
    data.update(overrides)
    return Settings(**data)
