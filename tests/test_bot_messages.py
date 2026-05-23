from app.bot_messages import signal_message
from app.order_flow import parse_signal_args


def test_signal_message_preserves_decimal_prices():
    signal = parse_signal_args(["PUMPUSDT", "long", "entry[0.00179", "0.00156]", "sl[0.0022]", "tp[0.00268]"])

    text = signal_message(signal, "kylekkkkwu")

    assert "**Entry：** 0.00179-0.00156" in text
    assert "**TP：** 0.00268" in text
    assert "**SL：** 0.0022" in text


def test_signal_message_uses_single_entry_price_when_range_is_not_provided():
    signal = parse_signal_args(["PUMPUSDT", "long", "entry[0.00179]", "sl[0.00156]", "tp[0.0022", "0.00268]"])

    text = signal_message(signal, "kylekkkkwu")

    assert "**Entry：** 0.00179" in text
    assert "**Entry：** 0.00179-0.00179" not in text


def test_signal_message_keeps_integer_prices_compact():
    signal = parse_signal_args(["BTCUSDT", "short", "entry[80200", "81000]", "sl[81700]", "tp[77777", "75000]"])

    text = signal_message(signal, "admin")

    assert "**Entry：** 81000-80200" in text
    assert "**TP：** 77777/75000" in text
    assert "**SL：** 81700" in text


def test_escape_markdown_ignores_dot_and_dash():
    from app.bot_messages import escape_markdown

    text = "加了一点仓位 止损设置到了2143.12 我这边加仓后的均价是2095.37 此时止损依旧是1R"
    escaped = escape_markdown(text)
    assert escaped == text  # Should be exactly the same

    special = "bold * italic _ code ` link ["
    escaped_special = escape_markdown(special)
    assert escaped_special == "bold \\* italic \\_ code \\` link \\["
