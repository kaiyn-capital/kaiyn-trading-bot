from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx


class BitgetAPIError(Exception):
    """Structured error raised for Bitget API responses and transport failures."""

    def __init__(
        self,
        code: str,
        message: str,
        data: dict | None = None,
        http_status: int | None = None,
        endpoint: str | None = None,
        method: str | None = None,
    ):
        self.code = code
        self.message = message
        self.data = data or {}
        self.http_status = http_status
        self.endpoint = endpoint
        self.method = method
        super().__init__(f"Bitget API Error [{code}]: {message}")


class BitgetErrorCategory(str, Enum):
    USER_CONFIG = "user_config"
    TRADING_PAIR = "trading_pair"
    EXCHANGE_REJECTED = "exchange_rejected"
    TEMPORARY_EXCHANGE = "temporary_exchange"
    NETWORK = "network"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedBitgetError:
    category: BitgetErrorCategory
    user_message: str
    raw_code: str | None = None
    raw_message: str | None = None
    http_status: int | None = None
    is_retryable: bool = False
    raw_data: Any | None = None

    def storage_message(self) -> str:
        parts = [f"category={self.category.value}"]
        if self.raw_code:
            parts.append(f"code={self.raw_code}")
        if self.http_status:
            parts.append(f"http_status={self.http_status}")
        if self.raw_message:
            parts.append(f"message={self.raw_message}")
        return " | ".join(parts)

    def to_log_data(self) -> dict:
        return {
            "category": self.category.value,
            "user_message": self.user_message,
            "raw_code": self.raw_code,
            "raw_message": self.raw_message,
            "http_status": self.http_status,
            "is_retryable": self.is_retryable,
            "raw_data": self.raw_data,
        }


USER_CONFIG_MESSAGE = "API 设置或权限异常，请检查 API Key 权限。"
TRADING_PAIR_MESSAGE = "交易对不存在或目前不可交易，请检查信号内容。"
EXCHANGE_REJECTED_MESSAGE = "交易所拒绝下单，请检查账户状态或参数。"
TEMPORARY_EXCHANGE_MESSAGE = "交易所或网络暂时异常，请稍后重新点击最新信号下单。"
NETWORK_MESSAGE = "网络连接异常，请稍后重新点击最新信号下单。"
UNKNOWN_MESSAGE = "发生未知错误，请联系管理员。"


def classify_bitget_exception(exc: Exception) -> ClassifiedBitgetError:
    if isinstance(exc, httpx.HTTPStatusError):
        http_status = exc.response.status_code if exc.response else None
        raw_message = str(exc)
        category = BitgetErrorCategory.TEMPORARY_EXCHANGE
        user_message = TEMPORARY_EXCHANGE_MESSAGE
        is_retryable = True
        if http_status in {401, 403}:
            category = BitgetErrorCategory.USER_CONFIG
            user_message = USER_CONFIG_MESSAGE
            is_retryable = False
        elif isinstance(http_status, int) and http_status < 500 and http_status != 429:
            category = BitgetErrorCategory.EXCHANGE_REJECTED
            user_message = EXCHANGE_REJECTED_MESSAGE
            is_retryable = False

        return ClassifiedBitgetError(
            category=category,
            user_message=user_message,
            raw_code=str(http_status) if http_status else None,
            raw_message=raw_message,
            http_status=http_status,
            is_retryable=is_retryable,
        )

    if isinstance(exc, httpx.TimeoutException):
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.NETWORK,
            user_message=NETWORK_MESSAGE,
            raw_message=str(exc),
            is_retryable=True,
        )

    if isinstance(exc, httpx.RequestError):
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.NETWORK,
            user_message=NETWORK_MESSAGE,
            raw_message=str(exc),
            is_retryable=True,
        )

    raw_code = _string_or_none(getattr(exc, "code", None))
    raw_message = _string_or_none(getattr(exc, "message", None)) or str(exc)
    http_status = getattr(exc, "http_status", None)
    raw_data = getattr(exc, "data", None)

    if isinstance(http_status, int) and http_status >= 500:
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.TEMPORARY_EXCHANGE,
            user_message=TEMPORARY_EXCHANGE_MESSAGE,
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            is_retryable=True,
            raw_data=raw_data,
        )

    if isinstance(http_status, int) and http_status == 429:
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.TEMPORARY_EXCHANGE,
            user_message=TEMPORARY_EXCHANGE_MESSAGE,
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            is_retryable=True,
            raw_data=raw_data,
        )

    if http_status in {401, 403}:
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.USER_CONFIG,
            user_message=USER_CONFIG_MESSAGE,
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            raw_data=raw_data,
        )

    message_for_matching = f"{raw_code or ''} {raw_message or ''}".lower()

    if raw_code in {"timeout", "network_error", "request_error"}:
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.NETWORK,
            user_message=NETWORK_MESSAGE,
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            is_retryable=True,
            raw_data=raw_data,
        )

    if _contains_any(
        message_for_matching,
        [
            "api key",
            "apikey",
            "access-key",
            "signature",
            "sign",
            "passphrase",
            "permission",
            "auth",
            "unauthorized",
            "forbidden",
            "invalid api",
            "invalid key",
            "invalid signature",
            "ip whitelist",
            "ip address",
            "ip not allowed",
            "权限",
            "签名",
            "密钥",
            "无效签名",
            "无效密钥",
        ],
    ):
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.USER_CONFIG,
            user_message=USER_CONFIG_MESSAGE,
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            raw_data=raw_data,
        )

    if _contains_any(
        message_for_matching,
        [
            "symbol",
            "contract",
            "instrument",
            "not exist",
            "not support",
            "unsupported",
            "交易对",
            "合约",
        ],
    ):
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.TRADING_PAIR,
            user_message=TRADING_PAIR_MESSAGE,
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            raw_data=raw_data,
        )

    if _contains_any(
        message_for_matching,
        [
            "timeout",
            "temporarily",
            "temporary",
            "busy",
            "try again",
            "rate limit",
            "too many",
            "system error",
            "系统",
            "繁忙",
            "稍后",
        ],
    ):
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.TEMPORARY_EXCHANGE,
            user_message=TEMPORARY_EXCHANGE_MESSAGE,
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            is_retryable=True,
            raw_data=raw_data,
        )

    if raw_code or _looks_like_bitget_api_error(exc):
        return ClassifiedBitgetError(
            category=BitgetErrorCategory.EXCHANGE_REJECTED,
            user_message=EXCHANGE_REJECTED_MESSAGE,
            raw_code=raw_code,
            raw_message=raw_message,
            http_status=http_status,
            raw_data=raw_data,
        )

    return ClassifiedBitgetError(
        category=BitgetErrorCategory.UNKNOWN,
        user_message=UNKNOWN_MESSAGE,
        raw_message=str(exc),
        raw_data=raw_data,
    )


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _looks_like_bitget_api_error(exc: Exception) -> bool:
    return isinstance(exc, BitgetAPIError) or exc.__class__.__name__ == "BitgetAPIError"


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
