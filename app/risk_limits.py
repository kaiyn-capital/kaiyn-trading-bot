from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from .config import Config

UTC_PLUS_8 = timezone(timedelta(hours=8))


@dataclass
class RiskLimitExceeded(Exception):
    """Raised when an order violates a hard local risk cap."""

    reason: str
    user_message: str
    details: dict[str, Any]

    def __str__(self) -> str:
        return self.user_message


def _positive_float_or_none(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_int_or_none(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def get_effective_position_limit(user_data) -> float:
    """Return the stricter positive position cap between global and user settings."""
    global_limit = _positive_float_or_none(Config.MAX_POSITION_SIZE) or 1000.0
    user_limit = _positive_float_or_none(getattr(user_data, "max_position_size", None))
    return min(global_limit, user_limit) if user_limit else global_limit


def get_effective_daily_trade_limit(user_data) -> int:
    """Return the stricter positive daily trade cap between global and user settings."""
    global_limit = _positive_int_or_none(Config.MAX_DAILY_TRADES) or 10
    user_limit = _positive_int_or_none(getattr(user_data, "daily_trade_limit", None))
    return min(global_limit, user_limit) if user_limit else global_limit


def get_daily_limit_day_start_utc(now: Optional[datetime] = None) -> datetime:
    """Return naive UTC datetime for the current UTC+8 trading day start."""
    now = now or datetime.utcnow()
    if now.tzinfo is None:
        now_utc = now.replace(tzinfo=timezone.utc)
    else:
        now_utc = now.astimezone(timezone.utc)

    local_now = now_utc.astimezone(UTC_PLUS_8)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=UTC_PLUS_8)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def build_position_limit_error(position_value: float, position_limit: float) -> RiskLimitExceeded:
    return RiskLimitExceeded(
        reason="position_size_limit_exceeded",
        user_message=(
            "❌ **仓位超过风险上限**\n\n"
            f"本次名义仓位为 ${position_value:.2f}，有效上限为 ${position_limit:.2f}。\n\n"
            "请降低 1R，或选择止损距离更大的信号。"
        ),
        details={
            "reason": "position_size_limit_exceeded",
            "position_value": position_value,
            "position_limit": position_limit,
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
            "❌ **今日下单次数已达上限**\n\n"
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


def ensure_position_within_limit(position_value: float, user_data) -> None:
    position_limit = get_effective_position_limit(user_data)
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
