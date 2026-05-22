from decimal import Decimal

import pytest

from app.order_flow import parse_signal_args, parse_tokenized_callback_data


def test_parse_signal_with_labeled_prices_and_remark():
    signal = parse_signal_args("BTCUSDT short entry[80200 81000] sl[81700] tp[77777 75000] 等待回踩后执行".split())

    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "short"
    assert signal.entry_lower == 80200
    assert signal.entry_upper == 81000
    assert signal.stop_loss == 81700
    assert signal.take_profit_levels == [77777, 75000]
    assert signal.remark == "等待回踩后执行"


def test_parse_signal_with_single_entry_price():
    signal = parse_signal_args("PUMPUSDT long entry[0.00179] sl[0.00156] tp[0.0022 0.00268]".split())

    assert signal.symbol == "PUMPUSDT"
    assert signal.direction == "long"
    assert signal.entry_lower == Decimal("0.00179")
    assert signal.entry_upper == Decimal("0.00179")
    assert signal.stop_loss == Decimal("0.00156")
    assert signal.take_profit_levels == [Decimal("0.0022"), Decimal("0.00268")]
    assert signal.remark == ""


def test_parse_tokenized_callback_data():
    order_mode, token = parse_tokenized_callback_data("place_order_limit_abc123")
    assert order_mode == "limit"
    assert token == "abc123"

    order_mode, token = parse_tokenized_callback_data("place_order_market_xyz789")
    assert order_mode == "market"
    assert token == "xyz789"

    with pytest.raises(ValueError):
        parse_tokenized_callback_data("place_order_invalid_abc123")

    with pytest.raises(ValueError):
        parse_tokenized_callback_data("place_order_market_")


def test_parse_signal_supports_case_insensitive_labels_and_spaced_brackets():
    signal = parse_signal_args("ethusdt LONG TP [3400 3500] ENTRY [3200 3250] SL [3150]".split())

    assert signal.symbol == "ETHUSDT"
    assert signal.direction == "long"
    assert signal.entry_lower == 3200
    assert signal.entry_upper == 3250
    assert signal.stop_loss == 3150
    assert signal.take_profit_levels == [3400, 3500]


def test_parse_signal_treats_text_outside_labels_as_remark():
    signal = parse_signal_args("PUMPUSDT long 等待 entry[0.00179] sl[0.00156] tp[0.0022] 回踩后执行".split())

    assert signal.remark == "等待 回踩后执行"


def test_parse_signal_rejects_old_positional_format():
    with pytest.raises(ValueError):
        parse_signal_args("BTCUSDT short 80200 81000 81700 77777".split())


@pytest.mark.parametrize(
    "command",
    [
        "BTCUSDT short entry[80200 81000] sl[81700]",
        "BTCUSDT short entry[80200 81000] tp[77777]",
        "BTCUSDT short sl[81700] tp[77777]",
        "BTCUSDT short entry[80200 81000 81100] sl[81700] tp[77777]",
        "BTCUSDT short entry[80200] sl[81700 81800] tp[77777]",
        "BTCUSDT short entry[80200] sl[81700] tp[]",
        "BTCUSDT short entry[80200] entry[81000] sl[81700] tp[77777]",
        "BTCUSDT neutral entry[80200] sl[81700] tp[77777]",
        "BTCUSDT short entry[bad] sl[81700] tp[77777]",
    ],
)
def test_parse_signal_rejects_invalid_labeled_format(command):
    with pytest.raises(ValueError):
        parse_signal_args(command.split())
