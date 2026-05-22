from decimal import Decimal

import pytest

from app.order_flow import OrderCallbackData, prepare_order_preview


def make_callback(**overrides):
    data = {
        "order_mode": "market",
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry_lower": 80200,
        "entry_upper": 81000,
        "stop_loss": 79000,
    }
    data.update(overrides)
    return OrderCallbackData(**data)


def test_market_preview_uses_current_price_for_1r_calculation():
    preview = prepare_order_preview(
        make_callback(order_mode="market", direction="long", stop_loss=79000),
        current_price=80000,
        risk_amount=100,
    )

    assert preview.order_mode == "market"
    assert preview.limit_price is None
    assert isinstance(preview.quantity, Decimal)
    assert preview.stop_distance_pct == Decimal("0.0125")
    assert preview.position_value == Decimal("8000")
    assert preview.quantity == Decimal("0.1")


def test_long_limit_uses_entry_high():
    preview = prepare_order_preview(
        make_callback(order_mode="limit", direction="long", stop_loss=79000),
        current_price=82000,
        risk_amount=100,
    )

    assert preview.order_mode == "limit"
    assert preview.limit_price == Decimal("81000")
    assert preview.position_value == Decimal("4050")
    assert isinstance(preview.quantity, Decimal)
    assert float(preview.quantity) == pytest.approx(0.05)


def test_short_limit_uses_entry_low():
    preview = prepare_order_preview(
        make_callback(order_mode="limit", direction="short", stop_loss=81700),
        current_price=79000,
        risk_amount=100,
    )

    assert preview.order_mode == "limit"
    assert preview.limit_price == Decimal("80200")
    assert isinstance(preview.position_value, Decimal)
    assert isinstance(preview.quantity, Decimal)
    assert float(preview.position_value) == pytest.approx(5346.666666666667)
    assert float(preview.quantity) == pytest.approx(0.0666666667)


def test_long_limit_switches_to_market_when_price_can_fill_immediately():
    preview = prepare_order_preview(
        make_callback(order_mode="limit", direction="long", stop_loss=79000),
        current_price=80000,
        risk_amount=100,
    )

    assert preview.requested_order_mode == "limit"
    assert preview.order_mode == "market"
    assert preview.limit_price is None
    assert preview.switch_notice


def test_short_limit_switches_to_market_when_price_can_fill_immediately():
    preview = prepare_order_preview(
        make_callback(order_mode="limit", direction="short", stop_loss=81700),
        current_price=80500,
        risk_amount=100,
    )

    assert preview.requested_order_mode == "limit"
    assert preview.order_mode == "market"
    assert preview.limit_price is None
    assert preview.switch_notice


def test_zero_stop_distance_is_rejected():
    with pytest.raises(ValueError):
        prepare_order_preview(
            make_callback(order_mode="market", direction="long", stop_loss=80000),
            current_price=80000,
            risk_amount=100,
        )
