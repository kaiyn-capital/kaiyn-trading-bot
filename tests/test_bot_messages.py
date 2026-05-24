from app.bot_messages import chart_update_message, signal_message
from app.order_flow import parse_signal_args


def test_signal_message_preserves_decimal_prices():
    signal = parse_signal_args(["PUMPUSDT", "long", "entry[0.00179", "0.00156]", "sl[0.0022]", "tp[0.00268]"])

    text = signal_message(signal, "kylekkkkwu")

    assert "<b>Entry：</b> 0.00179-0.00156" in text
    assert "<b>TP：</b> 0.00268" in text
    assert "<b>SL：</b> 0.0022" in text


def test_signal_message_uses_single_entry_price_when_range_is_not_provided():
    signal = parse_signal_args(["PUMPUSDT", "long", "entry[0.00179]", "sl[0.00156]", "tp[0.0022", "0.00268]"])

    text = signal_message(signal, "kylekkkkwu")

    assert "<b>Entry：</b> 0.00179" in text
    assert "<b>Entry：</b> 0.00179-0.00179" not in text


def test_signal_message_keeps_integer_prices_compact():
    signal = parse_signal_args(["BTCUSDT", "short", "entry[80200", "81000]", "sl[81700]", "tp[77777", "75000]"])

    text = signal_message(signal, "admin")

    assert "<b>Entry：</b> 81000-80200" in text
    assert "<b>TP：</b> 77777/75000" in text
    assert "<b>SL：</b> 81700" in text


def test_signal_message_escapes_free_text_as_html():
    signal = parse_signal_args(
        [
            "BTCUSDT",
            "long",
            "entry[80000]",
            "sl[79000]",
            "tp[82000]",
            "<b>公告</b>",
            "&",
            "wait",
        ]
    )

    text = signal_message(signal, "admin<root>", "sig<1>")

    assert "by @admin&lt;root&gt;" in text
    assert "&lt;b&gt;公告&lt;/b&gt; &amp; wait" in text
    assert "交易id: <code>sig&lt;1&gt;</code>" in text


def test_chart_update_message_escapes_remark_and_signal_id():
    text = chart_update_message("sig<1>", "<b>TP1 到达</b> & hold")

    assert "&lt;b&gt;TP1 到达&lt;/b&gt; &amp; hold" in text
    assert "交易id: <code>sig&lt;1&gt;</code>" in text
