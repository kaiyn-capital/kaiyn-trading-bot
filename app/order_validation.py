from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

from .decimal_utils import decimal_text, to_decimal
from .order_types import ContractRules, OrderPreview, OrderValidationResult


def _decimal_or_zero(value: object) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _int_or_zero(value: Any) -> int:
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


_decimal_text = decimal_text


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


def _validate_contract_rules(rules: ContractRules) -> OrderValidationResult | None:
    if not rules.symbol or rules.product_type != "USDT-FUTURES":
        return OrderValidationResult(False, "❌ 交易对不存在或不支持 U 本位合约")

    if rules.symbol_status.lower() != "normal":
        return OrderValidationResult(False, "❌ 交易对目前不可交易")

    return None


def _select_calculation_price(
    preview: OrderPreview,
) -> tuple[Decimal | None, OrderValidationResult | None]:
    calculation_price = (
        to_decimal(preview.limit_price)
        if preview.order_mode == "limit" and preview.limit_price is not None
        else to_decimal(preview.current_price)
    )

    if calculation_price <= 0:
        return None, OrderValidationResult(False, "❌ 进场价格错误，无法计算仓位")

    return calculation_price, None


def _validate_stop_loss_direction(
    direction: str,
    stop_loss: Decimal,
    calculation_price: Decimal,
) -> OrderValidationResult | None:
    if direction == "long" and stop_loss >= calculation_price:
        return OrderValidationResult(False, "❌ 止损方向不合理：做多止损必须低于进场价")

    if direction == "short" and stop_loss <= calculation_price:
        return OrderValidationResult(False, "❌ 止损方向不合理：做空止损必须高于进场价")

    return None


def _normalize_quantity(
    preview: OrderPreview,
    rules: ContractRules,
) -> tuple[Decimal | None, str | None, OrderValidationResult | None]:
    quantity = to_decimal(preview.quantity)
    if quantity <= 0:
        return None, None, OrderValidationResult(False, "❌ 下单数量错误，无法下单")

    if rules.size_multiplier > 0:
        quantity = _floor_to_step(quantity, rules.size_multiplier)
    quantity = _quantize_for_places(quantity, rules.volume_place)
    quantity_text = _decimal_text(quantity, rules.volume_place)

    if quantity <= 0:
        return None, None, OrderValidationResult(False, "❌ 下单数量低于交易所最小值")

    if rules.min_trade_num > 0 and quantity < rules.min_trade_num:
        return (
            None,
            None,
            OrderValidationResult(
                False,
                f"❌ 下单数量低于交易所最小值：至少 {_decimal_text(rules.min_trade_num)}",
            ),
        )

    max_qty = rules.max_market_order_qty if preview.order_mode == "market" else rules.max_order_qty
    if max_qty > 0 and quantity > max_qty:
        return (
            None,
            None,
            OrderValidationResult(
                False,
                f"❌ 下单数量超过交易所单笔上限：最多 {_decimal_text(max_qty)}",
            ),
        )

    return quantity, quantity_text, None


def _normalize_limit_price(
    preview: OrderPreview,
    rules: ContractRules,
    direction: str,
    calculation_price: Decimal,
) -> tuple[Decimal | None, Decimal | None, str | None, OrderValidationResult | None]:
    if preview.order_mode != "limit":
        return calculation_price, None, None, None

    if preview.limit_price is None or preview.limit_price <= 0:
        return (
            None,
            None,
            None,
            OrderValidationResult(False, "❌ 挂单价格错误，无法下单"),
        )

    limit_price_decimal = to_decimal(preview.limit_price)
    limit_price_decimal = _floor_to_step(limit_price_decimal, _price_step(rules))
    limit_price_decimal = _quantize_for_places(limit_price_decimal, rules.price_place)
    if limit_price_decimal <= 0:
        return (
            None,
            None,
            None,
            OrderValidationResult(False, "❌ 挂单价格错误，无法下单"),
        )

    current_price = to_decimal(preview.current_price)
    if (direction == "long" and limit_price_decimal >= current_price) or (
        direction == "short" and limit_price_decimal <= current_price
    ):
        return (
            None,
            None,
            None,
            OrderValidationResult(
                False,
                "❌ 挂单价已可能立即成交，请重新点击信号下单",
            ),
        )

    return (
        limit_price_decimal,
        limit_price_decimal,
        _decimal_text(limit_price_decimal, rules.price_place),
        None,
    )


def _validate_position_value(
    quantity: Decimal,
    calculation_price: Decimal,
    rules: ContractRules,
) -> tuple[Decimal | None, OrderValidationResult | None]:
    position_value_decimal = quantity * calculation_price
    if rules.min_trade_usdt > 0 and position_value_decimal < rules.min_trade_usdt:
        return (
            None,
            OrderValidationResult(
                False,
                f"❌ 下单名义价值低于交易所最小值：至少 {_decimal_text(rules.min_trade_usdt)} USDT",
            ),
        )

    return position_value_decimal, None


def validate_order_preview(
    preview: OrderPreview,
    rules: ContractRules,
    direction: str,
) -> OrderValidationResult:
    contract_error = _validate_contract_rules(rules)
    if contract_error:
        return contract_error

    calculation_price, calculation_error = _select_calculation_price(preview)
    if calculation_error:
        return calculation_error

    assert calculation_price is not None
    stop_loss_error = _validate_stop_loss_direction(direction, to_decimal(preview.stop_loss), calculation_price)
    if stop_loss_error:
        return stop_loss_error

    quantity, quantity_text, quantity_error = _normalize_quantity(preview, rules)
    if quantity_error:
        return quantity_error

    assert calculation_price is not None
    calculation_price, limit_price, limit_price_text, limit_price_error = _normalize_limit_price(
        preview,
        rules,
        direction,
        calculation_price,
    )
    if limit_price_error:
        return limit_price_error

    assert quantity is not None
    assert calculation_price is not None
    position_value_decimal, position_value_error = _validate_position_value(quantity, calculation_price, rules)
    if position_value_error:
        return position_value_error

    return OrderValidationResult(
        is_valid=True,
        quantity=quantity,
        quantity_text=quantity_text,
        limit_price=limit_price,
        limit_price_text=limit_price_text,
        position_value=position_value_decimal,
    )


def apply_order_validation(preview: OrderPreview, validation: OrderValidationResult) -> OrderPreview:
    if not validation.is_valid:
        return preview

    return replace(
        preview,
        quantity=(validation.quantity if validation.quantity is not None else preview.quantity),
        quantity_text=validation.quantity_text,
        limit_price=(validation.limit_price if preview.order_mode == "limit" else preview.limit_price),
        limit_price_text=validation.limit_price_text,
        position_value=(validation.position_value if validation.position_value is not None else preview.position_value),
    )
