from decimal import Decimal
from typing import Any

from .decimal_utils import decimal_text, to_decimal


def format_symbol(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "")


def validate_order_params(symbol: str, side: str, order_type: str, quantity: float, price: float | None = None) -> bool:
    if not symbol or not side or not order_type:
        return False

    if side not in ["buy", "sell"]:
        return False

    if order_type not in ["market", "limit"]:
        return False

    if quantity <= 0:
        return False

    if order_type == "limit":
        return price is not None and price > 0

    return True


def calculate_order_value(quantity: Any, price: Any) -> Decimal:
    return to_decimal(quantity) * to_decimal(price)


def format_price(price: Any, precision: int = 8) -> str:
    return decimal_text(price, precision)


def format_quantity(quantity: Any, precision: int = 8) -> str:
    return decimal_text(quantity, precision)
