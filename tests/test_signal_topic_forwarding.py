import asyncio
from types import SimpleNamespace

from app.bot_order_handlers import OrderHandlersMixin
from app.config import Config


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


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


class FakeOrderHandler(OrderHandlersMixin):
    def __init__(self):
        self.channel_repo = FakeChannelRepo()
        self.user = SimpleNamespace(telegram_id=123)
        self.audit_events = []

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


def test_send_signal_forwards_to_configured_topic(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", False)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    first_message = context.bot.sent_messages[0]
    assert first_message["chat_id"] == "-1001"
    assert first_message["message_thread_id"] == 456


def test_send_signal_without_topic_omits_message_thread_id(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", False)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    second_message = context.bot.sent_messages[1]
    assert second_message["chat_id"] == "-1002"
    assert "message_thread_id" not in second_message


def test_send_signal_records_audit_summary(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", False)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    audit = handler.audit_events[-1]
    assert audit["action"] == "signal_sent"
    assert audit["details"]["symbol"] == "BTCUSDT"
    assert audit["details"]["direction"] == "short"
    assert audit["details"]["remark"] == "等待回踩后执行"
    assert audit["details"]["target_count"] == 2
    assert audit["details"]["sent_count"] == 2
    assert audit["details"]["chart_status"] == "disabled"


def test_send_signal_sends_chart_photo_to_configured_topic(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", True)
    monkeypatch.setattr(Config, "SIGNAL_CHART_TIMEOUT_SECONDS", 1.0)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    first_photo = context.bot.sent_photos[0]
    assert first_photo["chat_id"] == "-1001"
    assert first_photo["message_thread_id"] == 456
    assert first_photo["caption"].startswith("🚨 **交易信号**")
    assert first_photo["parse_mode"] == "Markdown"
    assert first_photo["reply_markup"] is not None
    assert not context.bot.sent_messages
    assert handler.audit_events[-1]["details"]["chart_status"] == "generated"


def test_send_signal_falls_back_to_text_when_photo_send_fails(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", True)
    monkeypatch.setattr(Config, "SIGNAL_CHART_TIMEOUT_SECONDS", 1.0)
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()
    context.bot.fail_photo = True

    asyncio.run(handler.send_signal_command(update, context))

    assert len(context.bot.sent_messages) == 2
    assert context.bot.sent_messages[0]["message_thread_id"] == 456
    assert context.bot.sent_messages[0]["text"].startswith("🚨 **交易信号**")
    audit = handler.audit_events[-1]
    assert audit["details"]["sent_count"] == 2
    assert audit["details"]["chart_send_fallback_count"] == 2


def test_send_signal_falls_back_to_text_when_chart_generation_fails(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_CHART_ENABLED", True)
    monkeypatch.setattr(Config, "SIGNAL_CHART_TIMEOUT_SECONDS", 1.0)
    handler = FailingChartOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    assert len(context.bot.sent_messages) == 2
    assert not context.bot.sent_photos
    audit = handler.audit_events[-1]
    assert audit["details"]["chart_status"] == "failed"
    assert audit["details"]["chart_error"] == "RuntimeError"
    assert audit["details"]["sent_count"] == 2
