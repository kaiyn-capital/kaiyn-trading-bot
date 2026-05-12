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


def test_missing_symbol():
    assert_invalid(make_preview(), make_rules(symbol=""), "long")


def test_non_normal_symbol_status():
    assert_invalid(make_preview(), make_rules(symbolStatus="maintain"), "long")


def test_min_trade_num():
    assert_invalid(make_preview(quantity=0.0004), make_rules(), "long")


def test_min_trade_usdt():
    assert_invalid(
        make_preview(quantity=0.001, current_price=1000, position_value=1),
        make_rules(),
        "long",
    )


def test_quantity_is_formatted_to_multiplier():
    result = validate_order_preview(make_preview(quantity=0.012345), make_rules(), "long")
    assert result.is_valid
    assert result.quantity_text == "0.012"
    applied = apply_order_validation(make_preview(quantity=0.012345), result)
    assert applied.quantity == 0.012


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
    assert result.limit_price_text == "79999.9"


def test_market_order_max_quantity():
    assert_invalid(make_preview(quantity=2.001), make_rules(), "long")


def test_limit_order_max_quantity():
    preview = make_preview(
        requested_order_mode="limit",
        order_mode="limit",
        limit_price=79900,
        quantity=5.001,
        current_price=78000,
    )
    assert_invalid(preview, make_rules(), "long")


def test_long_stop_loss_must_be_below_entry():
    assert_invalid(make_preview(stop_loss=80000), make_rules(), "long")


def test_short_stop_loss_must_be_above_entry():
    assert_invalid(make_preview(stop_loss=80000), make_rules(), "short")


def test_limit_order_cannot_be_immediately_executable():
    preview = make_preview(
        requested_order_mode="limit",
        order_mode="limit",
        limit_price=81000,
        stop_loss=79000,
        current_price=80000,
    )
    assert_invalid(preview, make_rules(), "long")


def run_all():
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()


if __name__ == "__main__":
    run_all()
    print("order safety tests passed")
