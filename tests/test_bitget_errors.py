import httpx

from app.bitget_errors import BitgetErrorCategory, classify_bitget_exception


class FakeBitgetAPIError(Exception):
    def __init__(self, code, message, http_status=None, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data or {}


def test_invalid_api_key_is_user_config_error():
    result = classify_bitget_exception(
        FakeBitgetAPIError("40001", "invalid API key or signature")
    )

    assert result.category == BitgetErrorCategory.USER_CONFIG
    assert result.user_message == "API 设置或权限异常，请检查 API Key 权限。"


def test_unknown_symbol_is_trading_pair_error():
    result = classify_bitget_exception(
        FakeBitgetAPIError("40706", "symbol not exist")
    )

    assert result.category == BitgetErrorCategory.TRADING_PAIR
    assert "交易对" in result.user_message


def test_exchange_rejection_keeps_raw_code_and_message():
    result = classify_bitget_exception(
        FakeBitgetAPIError("43012", "insufficient balance")
    )

    assert result.category == BitgetErrorCategory.EXCHANGE_REJECTED
    assert result.raw_code == "43012"
    assert result.raw_message == "insufficient balance"
    assert "交易所拒绝下单" in result.user_message
    assert "code=43012" in result.storage_message()


def test_http_5xx_is_temporary_exchange_error():
    request = httpx.Request("GET", "https://api.bitget.com/test")
    response = httpx.Response(503, request=request)

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        result = classify_bitget_exception(exc)

    assert result.category == BitgetErrorCategory.TEMPORARY_EXCHANGE
    assert result.http_status == 503
    assert result.is_retryable is True


def test_http_403_is_user_config_error():
    result = classify_bitget_exception(
        FakeBitgetAPIError("403", "HTTP 403", http_status=403)
    )

    assert result.category == BitgetErrorCategory.USER_CONFIG
    assert result.is_retryable is False


def test_timeout_is_network_error():
    result = classify_bitget_exception(httpx.TimeoutException("request timed out"))

    assert result.category == BitgetErrorCategory.NETWORK
    assert result.is_retryable is True
    assert "网络连接异常" in result.user_message


def test_plain_exception_is_unknown_error():
    result = classify_bitget_exception(RuntimeError("boom"))

    assert result.category == BitgetErrorCategory.UNKNOWN
    assert result.user_message == "发生未知错误，请联系管理员。"
