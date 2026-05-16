from app.bot_messages import signal_message
from app.order_flow import parse_signal_args


def test_signal_message_preserves_decimal_prices():
    signal = parse_signal_args("PUMPUSDT long entry[0.00179 0.00156] sl[0.0022] tp[0.00268]".split())

    text = signal_message(signal, "kylekkkkwu")

    assert "**Entry：** 0.00179-0.00156" in text
    assert "**TP：** 0.00268" in text
    assert "**SL：** 0.0022" in text


def test_signal_message_uses_single_entry_price_when_range_is_not_provided():
    signal = parse_signal_args("PUMPUSDT long entry[0.00179] sl[0.00156] tp[0.0022 0.00268]".split())

    text = signal_message(signal, "kylekkkkwu")

    assert "**Entry：** 0.00179" in text
    assert "**Entry：** 0.00179-0.00179" not in text


def test_signal_message_keeps_integer_prices_compact():
    signal = parse_signal_args("BTCUSDT short entry[80200 81000] sl[81700] tp[77777 75000]".split())

    text = signal_message(signal, "admin")

    assert "**Entry：** 81000-80200" in text
    assert "**TP：** 77777/75000" in text
    assert "**SL：** 81700" in text
