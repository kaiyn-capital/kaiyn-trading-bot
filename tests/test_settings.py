from decimal import Decimal

import pytest
from settings_factory import make_settings

from app.config import Config
from app.settings import Settings


def complete_env(**overrides):
    data = {
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_ADMIN_IDS": "111, 222",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@postgres:5432/app",
        "ENCRYPTION_KEY": "secret",
    }
    data.update(overrides)
    return data


def test_settings_from_env_parses_runtime_values_without_dotenv():
    settings = Settings.from_env(
        complete_env(
            DEBUG="true",
            MAX_DAILY_TRADES="5",
            MAX_POSITION_SIZE="1000000.25",
            SIGNAL_CHART_ENABLED="false",
            SIGNAL_UPDATE_CANDLE_LIMIT="200",
            BITGET_API_URL="https://example.bitget.test",
        ),
        load_env_file=False,
    )

    assert settings.telegram_bot_token == "token"
    assert settings.admin_ids == (111, 222)
    assert settings.is_admin(111) is True
    assert settings.is_admin(333) is False
    assert settings.debug is True
    assert settings.max_daily_trades == 5
    assert settings.max_position_size == Decimal("1000000.25")
    assert settings.signal_chart_enabled is False
    assert settings.signal_update_candle_limit == 200
    assert settings.bitget_api_url == "https://example.bitget.test"


def test_settings_instances_are_explicit_snapshots_not_import_time_globals():
    first = Settings.from_env(complete_env(MAX_POSITION_SIZE="1000"), load_env_file=False)
    second = Settings.from_env(complete_env(MAX_POSITION_SIZE="1000000"), load_env_file=False)

    assert first.max_position_size == Decimal("1000")
    assert second.max_position_size == Decimal("1000000")


def test_settings_validate_requires_core_runtime_values():
    settings = Settings.from_env(complete_env(TELEGRAM_ADMIN_IDS=""), load_env_file=False)

    with pytest.raises(ValueError, match="Missing TELEGRAM_ADMIN_IDS"):
        settings.validate()


def test_settings_validate_requires_async_postgresql_url():
    settings = Settings.from_env(complete_env(DATABASE_URL="sqlite:///tmp.db"), load_env_file=False)

    with pytest.raises(ValueError, match="postgresql\\+asyncpg"):
        settings.validate_database_url()


def test_config_shim_can_be_reloaded_for_legacy_callers():
    original = Config.settings()
    try:
        Config.reload(make_settings(admin_ids=(999,), max_position_size=Decimal("1234")))

        assert Config.is_admin(999) is True
        assert Decimal("1234") == Config.MAX_POSITION_SIZE
    finally:
        Config.reload(original)
