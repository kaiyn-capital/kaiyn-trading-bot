from app.bot_account_formatters import format_usdt_balance_text


def test_format_usdt_balance_text_handles_list_payload_with_aliases():
    assets = [
        {"coin": "BTC", "available": "1", "frozen": "0"},
        {"marginCoin": "USDT", "availableBalance": "10.5", "freezeBalance": "2"},
    ]

    text = format_usdt_balance_text(assets, raw_limit=500, compact=True)

    assert "**USDT:**" in text
    assert "  可用: 10.5000" in text
    assert "  冻结: 2.0000" in text
    assert "  总计: 12.5000" in text
    assert "原始API数据" not in text


def test_format_usdt_balance_text_handles_dict_payload():
    assets = {"USDT": {"available": "20", "locked": "3.25"}}

    text = format_usdt_balance_text(assets, raw_limit=500, compact=False)

    assert "**USDT:**" in text
    assert "  可用: 20.0000" in text
    assert "  冻结: 3.2500" in text
    assert "  总计: 23.2500" in text


def test_format_usdt_balance_text_shows_limited_raw_data_when_empty():
    assets = {"USDT": {"available": "0", "frozen": "0"}, "BTC": {"available": "1"}}

    text = format_usdt_balance_text(assets, raw_limit=18, compact=True)

    assert "暂无 USDT 资产或余额为零" in text
    assert "📊 **原始API数据：**" in text
    assert f"{str(assets)[:18]}..." in text
    assert text.endswith("ℹ️ **说明：** 仅显示 U 本位合约账户的 USDT 余额")
