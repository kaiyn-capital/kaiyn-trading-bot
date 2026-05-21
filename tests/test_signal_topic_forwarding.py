import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.bot_order_handlers import OrderHandlersMixin
from app.bot_sessions import UserSessionMixin
from app.config import Config


class FakeMessage:
    def __init__(self):
        self.replies = []
        self.photos = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})

    async def reply_photo(self, **kwargs):
        self.photos.append(kwargs)


class FakeQuery:
    def __init__(self):
        self.caption_edits = []
        self.text_edits = []
        self.fail_caption_edit = False

    async def edit_message_caption(self, caption, **kwargs):
        if self.fail_caption_edit:
            raise RuntimeError("caption edit failed")
        self.caption_edits.append({"caption": caption, "kwargs": kwargs})

    async def edit_message_text(self, text, **kwargs):
        self.text_edits.append({"text": text, "kwargs": kwargs})


class FakeBot:
    def __init__(self):
        self.sent_messages = []
        self.sent_photos = []
        self.fail_photo = False

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)

    async def send_photo(self, **kwargs):
        if self.fail_photo:
            raise RuntimeError("photo failed")
        self.sent_photos.append(kwargs)


class FakeChannelRepo:
    async def get_signal_channels(self):
        return [
            {
                "chat_id": "-1001",
                "forward_with_buttons": True,
                "message_thread_id": 456,
            },
            {
                "chat_id": "-1002",
                "forward_with_buttons": True,
                "message_thread_id": None,
            },
        ]


class FakeOrderHandler(OrderHandlersMixin, UserSessionMixin):
    def __init__(self):
        self.channel_repo = FakeChannelRepo()
        self.user = SimpleNamespace(telegram_id=123)
        self.audit_events = []
        self.user_sessions = {}
        self.application = SimpleNamespace(bot=FakeBot())

    async def _get_or_create_user(self, update):
        return self.user

    async def _is_trader_or_admin(self, telegram_id):
        return True

    def _get_sender_username(self, update):
        return "admin"

    async def _audit_action(self, user, action, details=None):
        self.audit_events.append({"action": action, "details": details or {}})

    async def _create_signal_chart(self, signal):
        return b"fake-png"


class FailingChartOrderHandler(FakeOrderHandler):
    async def _create_signal_chart(self, signal):
        raise RuntimeError("chart failed")


def make_update():
    return SimpleNamespace(message=FakeMessage())


def make_context():
    return SimpleNamespace(
        args="BTCUSDT short entry[80200 81000] sl[81700] tp[77777 75000] 等待回踩后执行".split(),
        bot=FakeBot(),
    )


def test_send_signal_creates_text_preview_without_forwarding(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", False)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    assert context.bot.sent_messages == []
    assert handler.application.bot.sent_messages == []
    assert update.message.replies[0]["text"].startswith("📋 **请确认是否转发以下交易信号**")
    session = handler.user_sessions[handler.user.telegram_id]
    assert session["step"] == "signal_preview"
    assert session["signal"].symbol == "BTCUSDT"
    keyboard = update.message.replies[0]["kwargs"]["reply_markup"].inline_keyboard
    assert keyboard[0][0].callback_data == f"confirm_signal_{session['token']}"
    assert keyboard[1][0].callback_data == f"cancel_signal_{session['token']}"


def test_send_signal_records_preview_audit(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", False)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    audit = handler.audit_events[-1]
    assert audit["action"] == "signal_preview_created"
    assert audit["details"]["status"] == "pending"
    assert audit["details"]["symbol"] == "BTCUSDT"
    assert audit["details"]["direction"] == "short"
    assert audit["details"]["remark"] == "等待回踩后执行"
    assert audit["details"]["chart_status"] == "disabled"


def test_send_signal_sends_chart_photo_preview(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", True)
    monkeypatch.setattr(Config, "SIGNAL_CHART_TIMEOUT_SECONDS", 1.0)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    assert update.message.photos[0]["caption"].startswith("📋 **请确认是否转发以下交易信号**")
    assert update.message.photos[0]["parse_mode"] == "Markdown"
    assert update.message.photos[0]["reply_markup"] is not None
    assert handler.audit_events[-1]["details"]["chart_status"] == "generated"


def test_send_signal_falls_back_to_text_preview_when_chart_generation_fails(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", True)
    monkeypatch.setattr(Config, "SIGNAL_CHART_TIMEOUT_SECONDS", 1.0)
    handler = FailingChartOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    assert update.message.replies[0]["text"].startswith("📋 **请确认是否转发以下交易信号**")
    assert not update.message.photos
    audit = handler.audit_events[-1]
    assert audit["details"]["chart_status"] == "failed"
    assert audit["details"]["chart_error"] == "RuntimeError"


def test_confirm_signal_forwards_to_configured_topic(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", True)
    monkeypatch.setattr(Config, "SIGNAL_CHART_TIMEOUT_SECONDS", 1.0)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    query = FakeQuery()
    asyncio.run(handler._handle_confirm_signal_callback(query, handler.user, f"confirm_signal_{token}"))

    first_photo = handler.application.bot.sent_photos[0]
    assert first_photo["chat_id"] == "-1001"
    assert first_photo["message_thread_id"] == 456
    assert first_photo["caption"].startswith("🚨 **交易信号**")
    assert first_photo["parse_mode"] == "Markdown"
    assert first_photo["reply_markup"] is not None
    second_photo = handler.application.bot.sent_photos[1]
    assert second_photo["chat_id"] == "-1002"
    assert "message_thread_id" not in second_photo
    assert handler.user_sessions == {}
    assert query.caption_edits[-1]["caption"].startswith("✅ 交易信号已转发")
    assert handler.audit_events[-1]["action"] == "signal_sent"


def test_confirm_signal_falls_back_to_text_when_photo_send_fails(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", True)
    monkeypatch.setattr(Config, "SIGNAL_CHART_TIMEOUT_SECONDS", 1.0)
    handler = FakeOrderHandler()
    handler.application.bot.fail_photo = True
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    asyncio.run(handler._handle_confirm_signal_callback(FakeQuery(), handler.user, f"confirm_signal_{token}"))

    assert len(handler.application.bot.sent_messages) == 2
    assert handler.application.bot.sent_messages[0]["message_thread_id"] == 456
    assert handler.application.bot.sent_messages[0]["text"].startswith("🚨 **交易信号**")
    audit = handler.audit_events[-1]
    assert audit["details"]["sent_count"] == 2
    assert audit["details"]["chart_send_fallback_count"] == 2


def test_cancel_signal_clears_session_without_forwarding(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", False)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    query = FakeQuery()
    query.fail_caption_edit = True
    asyncio.run(handler._handle_cancel_signal_callback(query, handler.user, f"cancel_signal_{token}"))

    assert handler.user_sessions == {}
    assert handler.application.bot.sent_messages == []
    assert query.text_edits == [{"text": "✅ 已取消转发", "kwargs": {"reply_markup": None}}]
    assert handler.audit_events[-1]["action"] == "signal_preview_cancelled"


def test_expired_signal_preview_does_not_forward(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", False)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    handler.user_sessions[handler.user.telegram_id]["expires_at"] = datetime.utcnow() - timedelta(seconds=1)
    query = FakeQuery()
    query.fail_caption_edit = True
    asyncio.run(handler._handle_confirm_signal_callback(query, handler.user, f"confirm_signal_{token}"))

    assert handler.application.bot.sent_messages == []
    assert handler.user_sessions == {}
    assert query.text_edits[0]["text"].startswith("⏳ 预览已过期")
    assert handler.audit_events[-1]["action"] == "signal_preview_expired"


def test_new_signal_preview_replaces_old_token(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", False)
    handler = FakeOrderHandler()
    first_update = make_update()
    second_update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(first_update, context))
    old_token = handler.user_sessions[handler.user.telegram_id]["token"]
    asyncio.run(handler.send_signal_command(second_update, context))
    new_token = handler.user_sessions[handler.user.telegram_id]["token"]
    query = FakeQuery()
    query.fail_caption_edit = True
    asyncio.run(handler._handle_confirm_signal_callback(query, handler.user, f"confirm_signal_{old_token}"))

    assert old_token != new_token
    assert handler.application.bot.sent_messages == []
    assert query.text_edits[0]["text"].startswith("⏳ 预览已过期")
