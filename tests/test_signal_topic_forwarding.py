import asyncio
from types import SimpleNamespace

from app.bot_order_handlers import OrderHandlersMixin


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)


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


def make_update():
    return SimpleNamespace(message=FakeMessage())


def make_context():
    return SimpleNamespace(
        args="BTCUSDT short entry[80200 81000] sl[81700] tp[77777 75000] 等待回踩后执行".split(),
        bot=FakeBot(),
    )


def test_send_signal_forwards_to_configured_topic():
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    first_message = context.bot.sent_messages[0]
    assert first_message["chat_id"] == "-1001"
    assert first_message["message_thread_id"] == 456


def test_send_signal_without_topic_omits_message_thread_id():
    handler = FakeOrderHandler()
    update = make_update()
    context = make_context()

    asyncio.run(handler.send_signal_command(update, context))

    second_message = context.bot.sent_messages[1]
    assert second_message["chat_id"] == "-1002"
    assert "message_thread_id" not in second_message


def test_send_signal_records_audit_summary():
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
