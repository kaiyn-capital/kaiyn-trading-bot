from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class UserAccountRecord:
    id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    encrypted_api_key: str | None
    encrypted_secret_key: str | None
    encrypted_passphrase: str | None
    is_active: bool
    is_api_connected: bool
    daily_trade_limit: int | None
    max_position_size: Decimal | None
    default_stop_loss_percent: float | None
    default_trade_amount: float | None
    fixed_risk_amount: Decimal | None
    is_trader: bool
    created_at: datetime | None
    updated_at: datetime | None
    last_login: datetime | None


@dataclass(frozen=True)
class UserSummaryRecord:
    id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    is_api_connected: bool
    daily_trade_limit: int | None
    max_position_size: Decimal | None
    default_stop_loss_percent: float | None
    default_trade_amount: float | None
    fixed_risk_amount: Decimal | None
    is_trader: bool
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class UserSessionRecord:
    id: int
    telegram_id: int
    user_id: int | None
    session_type: str
    token: str | None
    payload_encrypted: str
    payload_version: int
    expires_at: datetime
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ChannelRecord:
    id: int
    chat_id: str
    chat_type: str
    title: str | None
    username: str | None
    is_active: bool
    auto_forward_signals: bool
    forward_with_buttons: bool
    message_thread_id: int | None
    thread_title: str | None
    added_by_user_id: int
    description: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class SignalRecordSnapshot:
    id: int
    public_id: str
    user_id: int | None
    sender_telegram_id: int
    sender_username: str | None
    symbol: str
    direction: str
    entry_lower: float
    entry_upper: float
    stop_loss: float
    take_profit_levels: list[float]
    remark: str | None
    signal_text: str
    granularity: str
    status: str
    chart_status: str | None
    chart_error: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


@dataclass(frozen=True)
class SignalChannelMessageRecord:
    id: int
    signal_record_id: int
    chat_id: str
    message_thread_id: int | None
    telegram_message_id: int
    sent_as: str
    created_at: datetime


@dataclass(frozen=True)
class PendingOrderRecord:
    id: int
    token: str
    user_id: int
    telegram_id: int
    symbol: str
    direction: str
    order_mode: str
    limit_price: Decimal | None
    entry_lower: Decimal | None
    entry_upper: Decimal | None
    quantity: Decimal
    stop_loss: Decimal
    position_value: Decimal
    current_price: Decimal
    status: str
    trade_id: int | None
    error_message: str | None
    created_at: datetime | None
    updated_at: datetime | None
    expires_at: datetime


@dataclass(frozen=True)
class TradeRecord:
    id: int
    user_id: int
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    price: Decimal | None
    bitget_order_id: str | None
    client_order_id: str | None
    status: str | None
    filled_quantity: Decimal | None
    avg_price: Decimal | None
    total_amount: Decimal | None
    fee: Decimal | None
    error_message: str | None
    created_at: datetime | None
    updated_at: datetime | None
    executed_at: datetime | None


@dataclass(frozen=True)
class NotificationRecord:
    id: int
    user_id: int | None
    message_type: str
    title: str
    message: str
    is_sent: bool
    telegram_message_id: int | None
    extra_data: dict[str, Any]
    created_at: datetime | None
    sent_at: datetime | None

    def get_extra_data(self) -> dict[str, Any]:
        return self.extra_data


@dataclass(frozen=True)
class SystemLogRecord:
    id: int
    level: str
    message: str
    module: str
    function: str | None
    user_id: int | None
    telegram_id: int | None
    extra_data: dict[str, Any]
    stack_trace: str | None
    created_at: datetime | None

    def get_extra_data(self) -> dict[str, Any]:
        return self.extra_data
