import re
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Optional, Sequence

from .bitget_errors import classify_bitget_exception


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


def _decimal_or_zero(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _quantize_for_places(value: Decimal, places: int) -> Decimal:
    if places <= 0:
        return value.quantize(Decimal("1"), rounding=ROUND_DOWN)
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _decimal_text(value: Decimal, places: Optional[int] = None) -> str:
    if places is not None:
        value = _quantize_for_places(value, places)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _price_step(rules: ContractRules) -> Decimal:
    if rules.price_end_step <= 0:
        return Decimal(1).scaleb(-rules.price_place)
    return rules.price_end_step * Decimal(1).scaleb(-rules.price_place)


def parse_contract_rules(payload: dict) -> ContractRules:
    return ContractRules(
        symbol=str(payload.get("symbol", "")).upper(),
        product_type=str(payload.get("productType") or "USDT-FUTURES").upper(),
        symbol_status=str(payload.get("symbolStatus") or ""),
        min_trade_num=_decimal_or_zero(payload.get("minTradeNum")),
        min_trade_usdt=_decimal_or_zero(payload.get("minTradeUSDT")),
        size_multiplier=_decimal_or_zero(payload.get("sizeMultiplier")),
        volume_place=_int_or_zero(payload.get("volumePlace")),
        price_place=_int_or_zero(payload.get("pricePlace")),
        price_end_step=_decimal_or_zero(payload.get("priceEndStep")),
        max_market_order_qty=_decimal_or_zero(payload.get("maxMarketOrderQty")),
        max_order_qty=_decimal_or_zero(payload.get("maxOrderQty")),
    )


def validate_order_preview(
    preview: OrderPreview,
    rules: ContractRules,
    direction: str,
) -> OrderValidationResult:
    if not rules.symbol or rules.product_type != "USDT-FUTURES":
        return OrderValidationResult(False, "❌ 交易对不存在或不支持 U 本位合约")

    if rules.symbol_status.lower() != "normal":
        return OrderValidationResult(False, "❌ 交易对目前不可交易")

    calculation_price = (
        Decimal(str(preview.limit_price))
        if preview.order_mode == "limit" and preview.limit_price is not None
        else Decimal(str(preview.current_price))
    )
    stop_loss = Decimal(str(preview.stop_loss))

    if calculation_price <= 0:
        return OrderValidationResult(False, "❌ 进场价格错误，无法计算仓位")

    if direction == "long" and stop_loss >= calculation_price:
        return OrderValidationResult(False, "❌ 止损方向不合理：做多止损必须低于进场价")

    if direction == "short" and stop_loss <= calculation_price:
        return OrderValidationResult(False, "❌ 止损方向不合理：做空止损必须高于进场价")

    quantity = Decimal(str(preview.quantity))
    if quantity <= 0:
        return OrderValidationResult(False, "❌ 下单数量错误，无法下单")

    if rules.size_multiplier > 0:
        quantity = _floor_to_step(quantity, rules.size_multiplier)
    quantity = _quantize_for_places(quantity, rules.volume_place)
    quantity_text = _decimal_text(quantity, rules.volume_place)

    if quantity <= 0:
        return OrderValidationResult(False, "❌ 下单数量低于交易所最小值")

    if rules.min_trade_num > 0 and quantity < rules.min_trade_num:
        return OrderValidationResult(
            False,
            f"❌ 下单数量低于交易所最小值：至少 {_decimal_text(rules.min_trade_num)}",
        )

    max_qty = rules.max_market_order_qty if preview.order_mode == "market" else rules.max_order_qty
    if max_qty > 0 and quantity > max_qty:
        return OrderValidationResult(
            False,
            f"❌ 下单数量超过交易所单笔上限：最多 {_decimal_text(max_qty)}",
        )

    limit_price = None
    limit_price_text = None
    if preview.order_mode == "limit":
        if preview.limit_price is None or preview.limit_price <= 0:
            return OrderValidationResult(False, "❌ 挂单价格错误，无法下单")

        limit_price_decimal = Decimal(str(preview.limit_price))
        limit_price_decimal = _floor_to_step(limit_price_decimal, _price_step(rules))
        limit_price_decimal = _quantize_for_places(limit_price_decimal, rules.price_place)
        if limit_price_decimal <= 0:
            return OrderValidationResult(False, "❌ 挂单价格错误，无法下单")

        if (direction == "long" and limit_price_decimal >= Decimal(str(preview.current_price))) or (
            direction == "short" and limit_price_decimal <= Decimal(str(preview.current_price))
        ):
            return OrderValidationResult(
                False,
                "❌ 挂单价已可能立即成交，请重新点击信号下单",
            )

        limit_price = float(limit_price_decimal)
        limit_price_text = _decimal_text(limit_price_decimal, rules.price_place)
        calculation_price = limit_price_decimal

    position_value_decimal = quantity * calculation_price
    if rules.min_trade_usdt > 0 and position_value_decimal < rules.min_trade_usdt:
        return OrderValidationResult(
            False,
            f"❌ 下单名义价值低于交易所最小值：至少 {_decimal_text(rules.min_trade_usdt)} USDT",
        )

    return OrderValidationResult(
        is_valid=True,
        quantity=float(quantity),
        quantity_text=quantity_text,
        limit_price=limit_price,
        limit_price_text=limit_price_text,
        position_value=float(position_value_decimal),
    )


def apply_order_validation(preview: OrderPreview, validation: OrderValidationResult) -> OrderPreview:
    if not validation.is_valid:
        return preview

    return replace(
        preview,
        quantity=validation.quantity if validation.quantity is not None else preview.quantity,
        quantity_text=validation.quantity_text,
        limit_price=(validation.limit_price if preview.order_mode == "limit" else preview.limit_price),
        limit_price_text=validation.limit_price_text,
        position_value=(validation.position_value if validation.position_value is not None else preview.position_value),
    )


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
