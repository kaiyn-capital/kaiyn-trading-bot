"""Compatibility exports for Bitget API modules.

New code should import from the focused modules directly. This module keeps
existing imports stable while the app is refactored in smaller steps.
"""

from .bitget_client import BitgetAPIClient
from .bitget_errors import BitgetAPIError
from .bitget_trade_manager import BitgetTradeManager
from .bitget_utils import (
    calculate_order_value,
    format_price,
    format_quantity,
    format_symbol,
    validate_order_params,
)

__all__ = [
    "BitgetAPIClient",
    "BitgetAPIError",
    "BitgetTradeManager",
    "calculate_order_value",
    "format_price",
    "format_quantity",
    "format_symbol",
    "validate_order_params",
]
