from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.config import Config
from app.risk_limits import (
    RiskLimitExceeded,
    ensure_daily_trade_limit_not_reached,
    ensure_position_within_limit,
    get_daily_limit_day_start_utc,
    get_effective_daily_trade_limit,
    get_effective_position_limit,
)


def test_effective_position_limit_uses_stricter_positive_cap(monkeypatch):
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 1000.0)

    assert get_effective_position_limit(SimpleNamespace(max_position_size=500.0)) == Decimal("500.0")
    assert get_effective_position_limit(SimpleNamespace(max_position_size=1500.0)) == Decimal("1000.0")
    assert get_effective_position_limit(SimpleNamespace(max_position_size=0)) == Decimal("1000.0")
    assert get_effective_position_limit(SimpleNamespace()) == Decimal("1000.0")


def test_effective_daily_trade_limit_uses_stricter_positive_cap(monkeypatch):
    monkeypatch.setattr(Config, "MAX_DAILY_TRADES", 10)

    assert get_effective_daily_trade_limit(SimpleNamespace(daily_trade_limit=3)) == 3
    assert get_effective_daily_trade_limit(SimpleNamespace(daily_trade_limit=30)) == 10
    assert get_effective_daily_trade_limit(SimpleNamespace(daily_trade_limit=0)) == 10
    assert get_effective_daily_trade_limit(SimpleNamespace()) == 10


def test_daily_limit_day_start_uses_utc_plus_8():
    assert get_daily_limit_day_start_utc(datetime(2026, 5, 22, 1, 30, 0)) == datetime(2026, 5, 21, 16, 0, 0)
    assert get_daily_limit_day_start_utc(datetime(2026, 5, 22, 18, 0, 0, tzinfo=timezone.utc)) == datetime(
        2026, 5, 22, 16, 0, 0
    )


def test_position_limit_raises_user_facing_error(monkeypatch):
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 1000.0)

    with pytest.raises(RiskLimitExceeded) as error:
        ensure_position_within_limit(1200.0, SimpleNamespace(max_position_size=1500.0))

    assert error.value.reason == "position_size_limit_exceeded"
    assert "仓位超过风险上限" in error.value.user_message
    assert error.value.details["position_limit"] == "1000"


def test_daily_trade_limit_raises_user_facing_error():
    with pytest.raises(RiskLimitExceeded) as error:
        ensure_daily_trade_limit_not_reached(
            current_count=10,
            daily_trade_limit=10,
            day_start_utc=datetime(2026, 5, 21, 16, 0, 0),
        )

    assert error.value.reason == "daily_trade_limit_exceeded"
    assert "今日下单次数已达上限" in error.value.user_message
    assert error.value.details["daily_trade_count"] == 10
    assert error.value.details["day_start_utc"] == "2026-05-21T16:00:00"
