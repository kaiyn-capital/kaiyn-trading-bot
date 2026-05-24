import hashlib
import re
import secrets
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from .bitget_errors import ClassifiedBitgetError, classify_bitget_exception
from .decimal_utils import decimal_text, to_decimal
from .order_types import (
    ContractRules,
    OrderCallbackData,
    OrderExecutionResult,
    OrderPreview,
    OrderValidationResult,
    SignalDraft,
)
from .order_validation import apply_order_validation, parse_contract_rules, validate_order_preview

__all__ = [
    "ContractRules",
    "OrderCallbackData",
    "OrderExecutionResult",
    "OrderExecutionUnknownResult",
    "OrderPreview",
    "OrderValidationResult",
    "SignalDraft",
    "apply_order_validation",
    "build_client_order_id",
    "execute_order",
    "parse_contract_rules",
    "parse_order_callback_data",
    "parse_tokenized_callback_data",
    "parse_signal_args",
    "prepare_order_preview",
    "validate_order_preview",
]


_SIGNAL_PRICE_GROUP_PATTERN = re.compile(r"\b(entry|sl|tp)\s*\[([^\]]*)\]", re.IGNORECASE)
_BITGET_CLIENT_ORDER_ID_PATTERN = re.compile(r"^[0-9A-Za-z_:#\-\+\s]{1,32}$")


class OrderExecutionUnknownResult(RuntimeError):
    """Raised when Bitget submission may have succeeded but no final response was received."""

    classified_error: ClassifiedBitgetError
    trade_id: int | None
    client_order_id: str

    def __init__(
        self,
        classified_error: ClassifiedBitgetError,
        trade_id: int | None,
        client_order_id: str,
    ) -> None:
        self.classified_error = classified_error
        self.trade_id = trade_id
        self.client_order_id = client_order_id
        super().__init__(classified_error.storage_message())


def build_client_order_id(pending_order_token: str | None = None) -> str:
    if pending_order_token:
        candidate = f"KTB_{pending_order_token}"
        if _BITGET_CLIENT_ORDER_ID_PATTERN.fullmatch(candidate):
            return candidate
        return f"KTB_{hashlib.sha256(pending_order_token.encode('utf-8')).hexdigest()[:24]}"

    return f"KTB_{secrets.token_urlsafe(16)}"


def _parse_signal_price_group(raw_prices: str) -> list[Decimal]:
    prices = raw_prices.split()
    if not prices:
        raise ValueError("missing signal price group values")

    try:
        return [to_decimal(price) for price in prices]
    except ValueError as exc:
        raise ValueError("invalid signal price") from exc


def parse_signal_args(args: Sequence[str]) -> SignalDraft:
    if len(args) < 3:
        raise ValueError("missing signal arguments")

    symbol = args[0].upper()
    direction = args[1].lower()
    if direction not in {"long", "short"}:
        raise ValueError("invalid signal direction")

    payload = " ".join(args[2:]).strip()
    matches = list(_SIGNAL_PRICE_GROUP_PATTERN.finditer(payload))
    if not matches:
        raise ValueError("missing labeled signal groups")

    groups: dict[str, list[Decimal]] = {}
    remark_parts = []
    last_end = 0
    for match in matches:
        label = match.group(1).lower()
        if label in groups:
            raise ValueError("duplicate signal group")

        remark_parts.append(payload[last_end : match.start()])
        groups[label] = _parse_signal_price_group(match.group(2))
        last_end = match.end()

    remark_parts.append(payload[last_end:])
    remark = " ".join(" ".join(remark_parts).split())

    if set(groups) != {"entry", "sl", "tp"}:
        raise ValueError("missing signal price group")

    entry_prices = groups["entry"]
    stop_losses = groups["sl"]
    take_profits = groups["tp"]

    if len(entry_prices) not in {1, 2}:
        raise ValueError("entry group must contain one or two prices")
    if len(stop_losses) != 1:
        raise ValueError("sl group must contain one price")

    entry_lower = min(entry_prices)
    entry_upper = max(entry_prices)
    stop_loss = stop_losses[0]

    return SignalDraft(
        symbol=symbol,
        direction=direction,
        entry_lower=entry_lower,
        entry_upper=entry_upper,
        stop_loss=stop_loss,
        take_profit_levels=take_profits,
        remark=remark,
    )


def parse_order_callback_data(data: str) -> OrderCallbackData:
    parts = data.split("_")
    if len(parts) >= 8 and parts[2] in {"market", "limit"}:
        order_mode = parts[2]
        symbol = parts[3]
        direction = parts[4]
        entry_lower = to_decimal(parts[5])
        entry_upper = to_decimal(parts[6])
        stop_loss = to_decimal(parts[7])
    elif len(parts) >= 7:
        order_mode = "market"
        symbol = parts[2]
        direction = parts[3]
        entry_lower = to_decimal(parts[4])
        entry_upper = to_decimal(parts[5])
        stop_loss = to_decimal(parts[6])
    else:
        raise ValueError("invalid order callback data")

    if order_mode not in {"market", "limit"} or direction not in {"long", "short"}:
        raise ValueError("invalid order callback data")

    return OrderCallbackData(
        order_mode=order_mode,
        symbol=symbol,
        direction=direction,
        entry_lower=entry_lower,
        entry_upper=entry_upper,
        stop_loss=stop_loss,
    )


def parse_tokenized_callback_data(data: str) -> tuple[str, str]:
    if data.startswith("place_order_market_"):
        order_mode = "market"
        token = data.removeprefix("place_order_market_")
    elif data.startswith("place_order_limit_"):
        order_mode = "limit"
        token = data.removeprefix("place_order_limit_")
    else:
        raise ValueError("invalid tokenized order callback data")

    if not token:
        raise ValueError("missing token in order callback data")

    return order_mode, token


def prepare_order_preview(
    callback_data: OrderCallbackData,
    current_price: Decimal | float,
    risk_amount: Decimal | float,
) -> OrderPreview:
    current_price = to_decimal(current_price)
    risk_amount = to_decimal(risk_amount)
    entry_low = min(callback_data.entry_lower, callback_data.entry_upper)
    entry_high = max(callback_data.entry_lower, callback_data.entry_upper)
    order_mode = callback_data.order_mode
    limit_price = None
    calculation_price = current_price
    switch_notice = None

    if order_mode == "limit":
        limit_price = entry_high if callback_data.direction == "long" else entry_low
        can_fill_immediately = (callback_data.direction == "long" and limit_price >= current_price) or (
            callback_data.direction == "short" and limit_price <= current_price
        )

        if can_fill_immediately:
            order_mode = "market"
            limit_price = None
            calculation_price = current_price
            switch_notice = "⚠️ 此挂单价已可能立即成交，已切换为市价下单确认。\n\n"
        else:
            calculation_price = limit_price

    if calculation_price <= 0:
        raise ValueError("entry price must be greater than 0")

    stop_distance = abs(calculation_price - callback_data.stop_loss)
    if stop_distance <= 0:
        raise ValueError("stop distance must be greater than 0")

    stop_distance_pct = stop_distance / calculation_price
    position_value = risk_amount * calculation_price / stop_distance
    quantity = position_value / calculation_price

    return OrderPreview(
        requested_order_mode=callback_data.order_mode,
        order_mode=order_mode,
        limit_price=limit_price,
        entry_lower=entry_low,
        entry_upper=entry_high,
        quantity=quantity,
        stop_loss=callback_data.stop_loss,
        position_value=position_value,
        current_price=current_price,
        risk_amount=risk_amount,
        stop_distance_pct=stop_distance_pct,
        switch_notice=switch_notice,
    )


async def execute_order(
    user_data: Any,
    trade_repo: Any,
    trade_manager: Any,
    credentials: tuple[str, str, str],
    telegram_id: int,
    symbol: str,
    direction: str,
    quantity: Decimal | float,
    stop_loss: Decimal | float,
    position_value: Decimal | float,
    order_mode: str = "market",
    limit_price: Decimal | float | None = None,
    quantity_text: str | None = None,
    limit_price_text: str | None = None,
    client_order_id: str | None = None,
    daily_trade_limit: int | None = None,
    daily_limit_day_start_utc: datetime | None = None,
) -> OrderExecutionResult:
    order_mode = order_mode if order_mode in {"market", "limit"} else "market"
    is_limit_order = order_mode == "limit"
    order_type = "limit" if is_limit_order else "market"
    order_price = to_decimal(limit_price) if is_limit_order and limit_price is not None else None
    if is_limit_order and (order_price is None or order_price <= 0):
        raise RuntimeError("Limit order is missing limit_price")

    side = "buy" if direction == "long" else "sell"
    quantity = to_decimal(quantity)
    stop_loss = to_decimal(stop_loss)
    position_value = to_decimal(position_value)
    quantity_for_api = quantity_text or decimal_text(quantity)
    price_for_api = limit_price_text or (decimal_text(order_price) if order_price is not None else None)
    client_order_id = client_order_id or build_client_order_id()
    trade_record_id: int | None = None
    exchange_submission_started = False

    try:
        trade_payload = {
            "user_id": user_data.id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "price": order_price,
            "client_order_id": client_order_id,
        }
        if daily_trade_limit is not None and daily_limit_day_start_utc is not None:
            trade_record = await trade_repo.create_trade_with_daily_limit(
                **trade_payload,
                daily_trade_limit=daily_trade_limit,
                day_start_utc=daily_limit_day_start_utc,
            )
        else:
            trade_record = await trade_repo.create_trade(**trade_payload)
        trade_record_id = trade_record.id

        if is_limit_order:
            exchange_submission_started = True
            result = await trade_manager.place_limit_order(
                user_data.id,
                credentials,
                symbol,
                side,
                quantity_for_api,
                price_for_api,
                client_order_id,
                "USDT",
                "open",
                stop_loss,
                force="gtc",
            )
        else:
            exchange_submission_started = True
            result = await trade_manager.place_market_order(
                user_data.id,
                credentials,
                symbol,
                side,
                quantity_for_api,
                client_order_id,
                "USDT",
                "open",
                stop_loss,
            )

        if not result or result.get("code") != "00000":
            error_msg = f"Order failed for {symbol}: {result.get('msg', 'Unknown error') if result else 'No response'}"
            raise RuntimeError(error_msg)

        order_data = result.get("data", {})
        bitget_order_id = order_data.get("orderId", "")
        status = "pending" if is_limit_order else "filled"

        await trade_repo.update_trade_result(
            trade_record_id,
            bitget_order_id=bitget_order_id,
            status=status,
        )

        return OrderExecutionResult(
            trade_id=trade_record_id,
            bitget_order_id=bitget_order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
            quantity=quantity,
            position_value=position_value,
            limit_price=order_price,
        )

    except Exception as exc:
        classified = classify_bitget_exception(exc)
        if exchange_submission_started and classified.is_retryable:
            raise OrderExecutionUnknownResult(classified, trade_record_id, client_order_id) from exc

        if trade_record_id is not None:
            await trade_repo.update_trade_result(
                trade_record_id,
                bitget_order_id=None,
                status="failed",
                error_message=classified.storage_message(),
            )
        raise
