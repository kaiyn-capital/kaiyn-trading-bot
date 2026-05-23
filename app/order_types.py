from dataclasses import dataclass
from decimal import Decimal

from .decimal_utils import to_decimal, to_decimal_or_none


@dataclass(frozen=True)
class SignalDraft:
    symbol: str
    direction: str
    entry_lower: Decimal
    entry_upper: Decimal
    stop_loss: Decimal
    take_profit_levels: list[Decimal]
    remark: str = ""

    def __post_init__(self):
        object.__setattr__(self, "entry_lower", to_decimal(self.entry_lower))
        object.__setattr__(self, "entry_upper", to_decimal(self.entry_upper))
        object.__setattr__(self, "stop_loss", to_decimal(self.stop_loss))
        object.__setattr__(self, "take_profit_levels", [to_decimal(tp) for tp in self.take_profit_levels])


@dataclass(frozen=True)
class OrderCallbackData:
    order_mode: str
    symbol: str
    direction: str
    entry_lower: Decimal
    entry_upper: Decimal
    stop_loss: Decimal

    def __post_init__(self):
        object.__setattr__(self, "entry_lower", to_decimal(self.entry_lower))
        object.__setattr__(self, "entry_upper", to_decimal(self.entry_upper))
        object.__setattr__(self, "stop_loss", to_decimal(self.stop_loss))


@dataclass(frozen=True)
class OrderPreview:
    requested_order_mode: str
    order_mode: str
    limit_price: Decimal | None
    entry_lower: Decimal
    entry_upper: Decimal
    quantity: Decimal
    stop_loss: Decimal
    position_value: Decimal
    current_price: Decimal
    risk_amount: Decimal
    stop_distance_pct: Decimal
    switch_notice: str | None = None
    quantity_text: str | None = None
    limit_price_text: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "limit_price", to_decimal_or_none(self.limit_price))
        object.__setattr__(self, "entry_lower", to_decimal(self.entry_lower))
        object.__setattr__(self, "entry_upper", to_decimal(self.entry_upper))
        object.__setattr__(self, "quantity", to_decimal(self.quantity))
        object.__setattr__(self, "stop_loss", to_decimal(self.stop_loss))
        object.__setattr__(self, "position_value", to_decimal(self.position_value))
        object.__setattr__(self, "current_price", to_decimal(self.current_price))
        object.__setattr__(self, "risk_amount", to_decimal(self.risk_amount))
        object.__setattr__(self, "stop_distance_pct", to_decimal(self.stop_distance_pct))


@dataclass(frozen=True)
class OrderExecutionResult:
    trade_id: int
    bitget_order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: Decimal
    position_value: Decimal
    limit_price: Decimal | None

    def __post_init__(self):
        object.__setattr__(self, "quantity", to_decimal(self.quantity))
        object.__setattr__(self, "position_value", to_decimal(self.position_value))
        object.__setattr__(self, "limit_price", to_decimal_or_none(self.limit_price))


@dataclass(frozen=True)
class ContractRules:
    symbol: str
    product_type: str
    symbol_status: str
    min_trade_num: Decimal
    min_trade_usdt: Decimal
    size_multiplier: Decimal
    volume_place: int
    price_place: int
    price_end_step: Decimal
    max_market_order_qty: Decimal
    max_order_qty: Decimal


@dataclass(frozen=True)
class OrderValidationResult:
    is_valid: bool
    error_message: str | None = None
    quantity: Decimal | None = None
    quantity_text: str | None = None
    limit_price: Decimal | None = None
    limit_price_text: str | None = None
    position_value: Decimal | None = None

    def __post_init__(self):
        object.__setattr__(self, "quantity", to_decimal_or_none(self.quantity))
        object.__setattr__(self, "limit_price", to_decimal_or_none(self.limit_price))
        object.__setattr__(self, "position_value", to_decimal_or_none(self.position_value))
