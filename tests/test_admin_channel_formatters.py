from app.bot_admin_channel_formatters import (
    admin_channels_keyboard,
    escape_html,
    format_admin_channels_html,
    format_channel_topic,
    format_manage_channels_html,
    manage_channels_keyboard,
)


def test_escape_html_handles_reserved_characters():
    assert escape_html("A&B <tag>") == "A&amp;B &lt;tag&gt;"


def test_format_channel_topic_uses_thread_title_or_default():
    assert format_channel_topic({"message_thread_id": None, "thread_title": None}) == "未设置"
    assert format_channel_topic({"message_thread_id": 456, "thread_title": "交易<信号>"}) == "交易&lt;信号&gt;"
    assert format_channel_topic({"message_thread_id": 456, "thread_title": None}) == "456"


def test_format_admin_channels_html_includes_channel_fields():
    text = format_admin_channels_html(
        [
            {
                "chat_id": "-1001",
                "chat_type": "supergroup",
                "title": "Kaiyn & Co",
                "username": "kaiyn_group",
                "auto_forward_signals": True,
                "message_thread_id": 456,
                "thread_title": "交易信号",
            }
        ]
    )

    assert "📺 <b>已管理的频道/群组</b>" in text
    assert "✅ <b>Kaiyn &amp; Co</b>" in text
    assert "类型: supergroup" in text
    assert "ID: <code>-1001</code>" in text
    assert "用户名: @kaiyn_group" in text
    assert "自动转发: 开启" in text
    assert "指定话题: 交易信号" in text


def test_format_admin_channels_html_shows_missing_topic_and_disabled_forwarding():
    text = format_admin_channels_html(
        [
            {
                "chat_id": "-1002",
                "chat_type": "channel",
                "title": None,
                "username": None,
                "auto_forward_signals": False,
                "message_thread_id": None,
                "thread_title": None,
            }
        ]
    )

    assert "❌ <b>Unknown</b>" in text
    assert "自动转发: 关闭" in text
    assert "指定话题: 未设置" in text


def test_format_manage_channels_html_keeps_number_and_username():
    text = format_manage_channels_html(
        [
            {
                "id": 1,
                "chat_id": "-1001",
                "title": "Kaiyn <Signals>",
                "username": "kaiyn_signals",
            }
        ]
    )

    assert "📺 <b>管理频道</b>" in text
    assert "1. Kaiyn &lt;Signals&gt; (@kaiyn_signals)" in text
    assert "请选择操作：" in text


def test_admin_channel_keyboards_keep_callback_data():
    admin_keyboard = admin_channels_keyboard().inline_keyboard
    manage_keyboard = manage_channels_keyboard().inline_keyboard

    assert admin_keyboard[0][0].callback_data == "add_new_channel"
    assert admin_keyboard[1][0].callback_data == "manage_channels"
    assert manage_keyboard[0][0].callback_data == "delete_channel_start"
    assert manage_keyboard[1][0].callback_data == "return_admin_channels"
