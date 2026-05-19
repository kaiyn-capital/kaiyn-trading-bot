from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class SignalDraft:
    symbol: str
    direction: str
    entry_lower: float
    entry_upper: float
    stop_loss: float
    take_profit_levels: list[float]
    remark: str = ""


@dataclass(frozen=True)
class OrderCallbackData:
    order_mode: str
    symbol: str
    direction: str
    entry_lower: float
    entry_upper: float
    stop_loss: float


@dataclass(frozen=True)
class OrderPreview:
    requested_order_mode: str
    order_mode: str
    limit_price: Optional[float]
    entry_lower: float
    entry_upper: float
    quantity: float
    stop_loss: float
    position_value: float
    current_price: float
    risk_amount: float
    stop_distance_pct: float
    switch_notice: Optional[str] = None
    quantity_text: Optional[str] = None
    limit_price_text: Optional[str] = None


@dataclass(frozen=True)
class OrderExecutionResult:
    trade_id: int
    bitget_order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: float
    position_value: float
    limit_price: Optional[float]


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
    error_message: Optional[str] = None
    quantity: Optional[float] = None
    quantity_text: Optional[str] = None
    limit_price: Optional[float] = None
    limit_price_text: Optional[str] = None
    position_value: Optional[float] = None
