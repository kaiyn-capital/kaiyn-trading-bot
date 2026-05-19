import re
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from .bitget_errors import classify_bitget_exception
from .order_types import (
    ContractRules,
    OrderCallbackData,
    OrderExecutionResult,
    OrderPreview,
    OrderValidationResult,
    SignalDraft,
)
from .order_validation import _decimal_text, apply_order_validation, parse_contract_rules, validate_order_preview

__all__ = [
    "ContractRules",
    "OrderCallbackData",
    "OrderExecutionResult",
    "OrderPreview",
    "OrderValidationResult",
    "SignalDraft",
    "apply_order_validation",
    "execute_order",
    "parse_contract_rules",
    "parse_order_callback_data",
    "parse_signal_args",
    "prepare_order_preview",
    "validate_order_preview",
]


_SIGNAL_PRICE_GROUP_PATTERN = re.compile(r"\b(entry|sl|tp)\s*\[([^\]]*)\]", re.IGNORECASE)


def _parse_signal_price_group(raw_prices: str) -> list[float]:
    prices = raw_prices.split()
    if not prices:
        raise ValueError("missing signal price group values")

    try:
        return [float(price) for price in prices]
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

    groups: dict[str, list[float]] = {}
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
        entry_lower = float(parts[5])
        entry_upper = float(parts[6])
        stop_loss = float(parts[7])
    elif len(parts) >= 7:
        order_mode = "market"
        symbol = parts[2]
        direction = parts[3]
        entry_lower = float(parts[4])
        entry_upper = float(parts[5])
        stop_loss = float(parts[6])
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


def prepare_order_preview(
    callback_data: OrderCallbackData,
    current_price: float,
    risk_amount: float,
) -> OrderPreview:
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

    stop_distance_pct = abs((calculation_price - callback_data.stop_loss) / calculation_price)
    if stop_distance_pct <= 0:
        raise ValueError("stop distance must be greater than 0")

    position_value = risk_amount / stop_distance_pct
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
    user_data,
    trade_repo,
    trade_manager,
    credentials,
    telegram_id: int,
    symbol: str,
    direction: str,
    quantity: float,
    stop_loss: float,
    position_value: float,
    order_mode: str = "market",
    limit_price: Optional[float] = None,
    quantity_text: Optional[str] = None,
    limit_price_text: Optional[str] = None,
) -> OrderExecutionResult:
    order_mode = order_mode if order_mode in {"market", "limit"} else "market"
    is_limit_order = order_mode == "limit"
    order_type = "limit" if is_limit_order else "market"
    order_price = limit_price if is_limit_order else None
    if is_limit_order and not order_price:
        raise RuntimeError("Limit order is missing limit_price")

    side = "buy" if direction == "long" else "sell"
    quantity = float(quantity)
    quantity_for_api = quantity_text or _decimal_text(Decimal(str(quantity)))
    price_for_api = limit_price_text or (_decimal_text(Decimal(str(order_price))) if order_price is not None else None)
    client_order_id = f"TG_{telegram_id}_{int(datetime.timestamp(datetime.now()))}"
    trade_record_id = None

    try:
        trade_record = await trade_repo.create_trade(
            user_id=user_data.id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=order_price,
            client_order_id=client_order_id,
        )
        trade_record_id = trade_record.id

        if is_limit_order:
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
        if trade_record_id is not None:
            await trade_repo.update_trade_result(
                trade_record_id,
                bitget_order_id=None,
                status="failed",
                error_message=classified.storage_message(),
            )
        raise
