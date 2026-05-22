from decimal import Decimal

from app.order_flow import (
    OrderPreview,
    apply_order_validation,
    parse_contract_rules,
    validate_order_preview,
)


def make_rules(**overrides):
    payload = {
        "symbol": "BTCUSDT",
        "productType": "USDT-FUTURES",
        "symbolStatus": "normal",
        "minTradeNum": "0.001",
        "minTradeUSDT": "5",
        "sizeMultiplier": "0.001",
        "volumePlace": "3",
        "pricePlace": "1",
        "priceEndStep": "1",
        "maxMarketOrderQty": "2",
        "maxOrderQty": "5",
    }
    payload.update(overrides)
    return parse_contract_rules(payload)


def make_preview(**overrides):
    preview = {
        "requested_order_mode": "market",
        "order_mode": "market",
        "limit_price": None,
        "entry_lower": 80000,
        "entry_upper": 81000,
        "quantity": 0.01,
        "stop_loss": 79000,
        "position_value": 800,
        "current_price": 80000,
        "risk_amount": 100,
        "stop_distance_pct": 0.0125,
    }
    preview.update(overrides)
    return OrderPreview(**preview)


def assert_invalid(preview, rules, direction):
    result = validate_order_preview(preview, rules, direction)
    assert not result.is_valid
    assert result.error_message
    return result


def test_missing_symbol():
    result = assert_invalid(make_preview(), make_rules(symbol=""), "long")
    assert result.error_message == "❌ 交易对不存在或不支持 U 本位合约"


def test_unsupported_product_type():
    result = assert_invalid(make_preview(), make_rules(productType="COIN-FUTURES"), "long")
    assert result.error_message == "❌ 交易对不存在或不支持 U 本位合约"


def test_non_normal_symbol_status():
    result = assert_invalid(make_preview(), make_rules(symbolStatus="maintain"), "long")
    assert result.error_message == "❌ 交易对目前不可交易"


def test_min_trade_num():
    result = assert_invalid(make_preview(quantity=0.001), make_rules(minTradeNum="0.002"), "long")
    assert result.error_message == "❌ 下单数量低于交易所最小值：至少 0.002"


def test_min_trade_usdt():
    result = assert_invalid(
        make_preview(quantity=0.001, current_price=1000, stop_loss=900, position_value=1),
        make_rules(),
        "long",
    )
    assert result.error_message == "❌ 下单名义价值低于交易所最小值：至少 5 USDT"


def test_quantity_must_be_positive():
    result = assert_invalid(make_preview(quantity=0), make_rules(), "long")
    assert result.error_message == "❌ 下单数量错误，无法下单"


def test_quantity_floor_to_zero_is_below_exchange_minimum():
    result = assert_invalid(make_preview(quantity=0.0004), make_rules(), "long")
    assert result.error_message == "❌ 下单数量低于交易所最小值"


def test_quantity_is_formatted_to_multiplier():
    result = validate_order_preview(make_preview(quantity=0.012345), make_rules(), "long")
    assert result.is_valid
    assert result.quantity_text == "0.012"
    applied = apply_order_validation(make_preview(quantity=0.012345), result)
    assert applied.quantity == Decimal("0.012")


def test_limit_price_is_formatted_to_price_step():
    preview = make_preview(
        requested_order_mode="limit",
        order_mode="limit",
        limit_price=79999.99,
        stop_loss=79000,
        current_price=81000,
    )
    result = validate_order_preview(preview, make_rules(), "long")
    assert result.is_valid
    assert result.limit_price == Decimal("79999.9")
    assert result.limit_price_text == "79999.9"


def test_market_order_max_quantity():
    result = assert_invalid(make_preview(quantity=2.001), make_rules(), "long")
    assert result.error_message == "❌ 下单数量超过交易所单笔上限：最多 2"


def test_limit_order_max_quantity():
    preview = make_preview(
        requested_order_mode="limit",
        order_mode="limit",
        limit_price=79900,
        quantity=5.001,
        current_price=78000,
    )
    result = assert_invalid(preview, make_rules(), "long")
    assert result.error_message == "❌ 下单数量超过交易所单笔上限：最多 5"


def test_long_stop_loss_must_be_below_entry():
    result = assert_invalid(make_preview(stop_loss=80000), make_rules(), "long")
    assert result.error_message == "❌ 止损方向不合理：做多止损必须低于进场价"


def test_short_stop_loss_must_be_above_entry():
    result = assert_invalid(make_preview(stop_loss=80000), make_rules(), "short")
    assert result.error_message == "❌ 止损方向不合理：做空止损必须高于进场价"


def test_limit_order_requires_limit_price():
    preview = make_preview(
        requested_order_mode="limit",
        order_mode="limit",
        limit_price=None,
        stop_loss=79000,
        current_price=80000,
    )
    result = assert_invalid(preview, make_rules(), "long")
    assert result.error_message == "❌ 挂单价格错误，无法下单"


def test_limit_price_floor_to_zero_is_rejected():
    preview = make_preview(
        requested_order_mode="limit",
        order_mode="limit",
        limit_price=0.04,
        stop_loss=0.01,
        current_price=1,
    )
    result = assert_invalid(preview, make_rules(pricePlace="0", priceEndStep="1", minTradeUSDT="0"), "long")
    assert result.error_message == "❌ 挂单价格错误，无法下单"


def test_limit_order_cannot_be_immediately_executable():
    preview = make_preview(
        requested_order_mode="limit",
        order_mode="limit",
        limit_price=81000,
        stop_loss=79000,
        current_price=80000,
    )
    result = assert_invalid(preview, make_rules(), "long")
    assert result.error_message == "❌ 挂单价已可能立即成交，请重新点击信号下单"
