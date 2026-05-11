from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence


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


def parse_signal_args(args: Sequence[str]) -> SignalDraft:
    if len(args) < 6:
        raise ValueError("missing signal arguments")

    symbol = args[0].upper()
    direction = args[1].lower()
    entry_lower = float(args[2])
    entry_upper = float(args[3])
    stop_loss = float(args[4])

    take_profits = []
    remark_start_index = None
    for index in range(5, len(args)):
        try:
            take_profits.append(float(args[index]))
        except ValueError:
            remark_start_index = index
            break

    remark = (
        " ".join(args[remark_start_index:]).strip()
        if remark_start_index is not None
        else ""
    )

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
        can_fill_immediately = (
            callback_data.direction == "long" and limit_price >= current_price
        ) or (callback_data.direction == "short" and limit_price <= current_price)

        if can_fill_immediately:
            order_mode = "market"
            limit_price = None
            calculation_price = current_price
            switch_notice = "⚠️ 此挂单价已可能立即成交，已切换为市价下单确认。\n\n"
        else:
            calculation_price = limit_price

    if calculation_price <= 0:
        raise ValueError("entry price must be greater than 0")

    stop_distance_pct = abs(
        (calculation_price - callback_data.stop_loss) / calculation_price
    )
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
) -> OrderExecutionResult:
    order_mode = order_mode if order_mode in {"market", "limit"} else "market"
    is_limit_order = order_mode == "limit"
    order_type = "limit" if is_limit_order else "market"
    order_price = limit_price if is_limit_order else None
    if is_limit_order and not order_price:
        raise RuntimeError("Limit order is missing limit_price")

    side = "buy" if direction == "long" else "sell"
    quantity = round(quantity, 6)
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
                str(quantity),
                str(order_price),
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
                str(quantity),
                client_order_id,
                "USDT",
                "open",
                stop_loss,
            )

        if not result or result.get("code") != "00000":
            error_msg = (
                f"Order failed for {symbol}: "
                f"{result.get('msg', 'Unknown error') if result else 'No response'}"
            )
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
        if trade_record_id is not None:
            await trade_repo.update_trade_result(
                trade_record_id,
                bitget_order_id=None,
                status="failed",
                error_message=str(exc),
            )
        raise
