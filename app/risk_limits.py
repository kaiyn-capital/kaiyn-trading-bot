from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from .decimal_utils import decimal_json, to_decimal_or_none
from .time_utils import utc_now_naive

UTC_PLUS_8 = timezone(timedelta(hours=8))


@dataclass
class RiskLimitExceeded(Exception):
    """Raised when an order violates a hard local risk cap."""

    reason: str
    user_message: str
    details: dict[str, Any]

    def __str__(self) -> str:
        return self.user_message


def _positive_decimal_or_none(value: Any) -> Decimal | None:
    parsed = to_decimal_or_none(value)
    if parsed is None:
        return None
    return parsed if parsed > 0 else None


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def get_effective_position_limit(user_data: object, global_max_position_size: Any = Decimal("1000.0")) -> Decimal:
    """Return the stricter positive position cap between global and user settings."""
    global_limit = _positive_decimal_or_none(global_max_position_size) or Decimal("1000.0")
    user_limit = _positive_decimal_or_none(getattr(user_data, "max_position_size", None))
    return min(global_limit, user_limit) if user_limit else global_limit


def get_effective_daily_trade_limit(user_data: object, global_daily_trade_limit: Any = 10) -> int:
    """Return the stricter positive daily trade cap between global and user settings."""
    global_limit = _positive_int_or_none(global_daily_trade_limit) or 10
    user_limit = _positive_int_or_none(getattr(user_data, "daily_trade_limit", None))
    return min(global_limit, user_limit) if user_limit else global_limit


def get_daily_limit_day_start_utc(now: datetime | None = None) -> datetime:
    """Return naive UTC datetime for the current UTC+8 trading day start."""
    now = now or utc_now_naive()
    if now.tzinfo is None:
        now_utc = now.replace(tzinfo=UTC)
    else:
        now_utc = now.astimezone(UTC)

    local_now = now_utc.astimezone(UTC_PLUS_8)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=UTC_PLUS_8)
    return local_start.astimezone(UTC).replace(tzinfo=None)


def build_position_limit_error(position_value: Decimal, position_limit: Decimal) -> RiskLimitExceeded:
    return RiskLimitExceeded(
        reason="position_size_limit_exceeded",
        user_message=(
            "❌ <b>仓位超过风险上限</b>\n\n"
            f"本次名义仓位为 ${position_value:.2f}，有效上限为 ${position_limit:.2f}。\n\n"
            "请降低 1R，或选择止损距离更大的信号。"
        ),
        details={
            "reason": "position_size_limit_exceeded",
            "position_value": decimal_json(position_value),
            "position_limit": decimal_json(position_limit),
        },
    )


def build_daily_trade_limit_error(
    *,
    current_count: int,
    daily_trade_limit: int,
    day_start_utc: datetime,
) -> RiskLimitExceeded:
    return RiskLimitExceeded(
        reason="daily_trade_limit_exceeded",
        user_message=(
            "❌ <b>今日下单次数已达上限</b>\n\n"
            f"今日已送出 {current_count} 笔，下单上限为 {daily_trade_limit} 笔。\n\n"
            "请明天再试，或联系管理员调整交易限制。"
        ),
        details={
            "reason": "daily_trade_limit_exceeded",
            "daily_trade_count": current_count,
            "daily_trade_limit": daily_trade_limit,
            "day_start_utc": day_start_utc.isoformat(),
        },
    )


def ensure_position_within_limit(
    position_value: Decimal | float,
    user_data: object,
    global_max_position_size: Any = Decimal("1000.0"),
) -> None:
    position_value = _positive_decimal_or_none(position_value) or Decimal("0")
    position_limit = get_effective_position_limit(user_data, global_max_position_size)
    if position_value > position_limit:
        raise build_position_limit_error(position_value, position_limit)


def ensure_daily_trade_limit_not_reached(
    *,
    current_count: int,
    daily_trade_limit: int,
    day_start_utc: datetime,
) -> None:
    if current_count >= daily_trade_limit:
        raise build_daily_trade_limit_error(
            current_count=current_count,
            daily_trade_limit=daily_trade_limit,
            day_start_utc=day_start_utc,
        )
