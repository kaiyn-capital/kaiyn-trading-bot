import pytest

from app.order_flow import parse_signal_args


def test_parse_signal_with_multiple_take_profits_and_remark():
    signal = parse_signal_args(
        "BTCUSDT short 80200 81000 81700 77777 75000 等待回踩后执行".split()
    )

    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "short"
    assert signal.entry_lower == 80200
    assert signal.entry_upper == 81000
    assert signal.stop_loss == 81700
    assert signal.take_profit_levels == [77777, 75000]
    assert signal.remark == "等待回踩后执行"


def test_parse_signal_without_remark():
    signal = parse_signal_args(
        "ETHUSDT long 3200 3250 3150 3400 3500 3600".split()
    )

    assert signal.symbol == "ETHUSDT"
    assert signal.direction == "long"
    assert signal.take_profit_levels == [3400, 3500, 3600]
    assert signal.remark == ""


def test_parse_signal_uppercases_symbol_and_lowercases_direction():
    signal = parse_signal_args("btcusdt LONG 80200 81000 79000 83000".split())

    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "long"


def test_parse_signal_requires_minimum_arguments():
    with pytest.raises(ValueError):
        parse_signal_args("BTCUSDT short 80200 81000 81700".split())


def test_parse_signal_rejects_invalid_numeric_fields():
    with pytest.raises(ValueError):
        parse_signal_args("BTCUSDT short bad 81000 81700 77777".split())
