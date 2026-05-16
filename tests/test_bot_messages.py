from app.bot_messages import signal_message
from app.order_flow import parse_signal_args


def test_signal_message_preserves_decimal_prices():
    signal = parse_signal_args("PUMPUSDT long 0.00179 0.00156 0.0022 0.00268".split())

    text = signal_message(signal, "kylekkkkwu")

    assert "**Entry：** 0.00156-0.00179" in text
    assert "**TP：** 0.00268" in text
    assert "**SL：** 0.0022" in text


def test_signal_message_keeps_integer_prices_compact():
    signal = parse_signal_args("BTCUSDT short 80200 81000 81700 77777 75000".split())

    text = signal_message(signal, "admin")

    assert "**Entry：** 81000-80200" in text
    assert "**TP：** 77777/75000" in text
    assert "**SL：** 81700" in text
