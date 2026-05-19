from app.bitget_api import (
    BitgetAPIClient,
    BitgetAPIError,
    BitgetTradeManager,
    calculate_order_value,
    format_price,
    format_quantity,
    format_symbol,
    validate_order_params,
)
from app.bitget_client import BitgetAPIClient as FocusedBitgetAPIClient
from app.bitget_errors import BitgetAPIError as FocusedBitgetAPIError
from app.bitget_errors import BitgetErrorCategory, classify_bitget_exception
from app.bitget_trade_manager import BitgetTradeManager as FocusedBitgetTradeManager


def test_bitget_api_facade_exports_existing_public_symbols():
    assert BitgetAPIClient is FocusedBitgetAPIClient
    assert BitgetAPIError is FocusedBitgetAPIError
    assert BitgetTradeManager is FocusedBitgetTradeManager
    assert format_symbol("btc/usdt") == "BTCUSDT"
    assert validate_order_params("BTCUSDT", "buy", "market", 0.01) is True
    assert calculate_order_value(2, 3) == 6
    assert format_price(1.23000000) == "1.23"
    assert format_quantity(0.10000000) == "0.1"


def test_real_bitget_api_error_is_classified_directly():
    error = FocusedBitgetAPIError("40001", "invalid API key or signature", http_status=403)

    result = classify_bitget_exception(error)

    assert result.category == BitgetErrorCategory.USER_CONFIG
    assert result.raw_code == "40001"
    assert result.http_status == 403
