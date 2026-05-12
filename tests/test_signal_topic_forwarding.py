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

    async def _get_or_create_user(self, update):
        return self.user

    async def _is_trader_or_admin(self, telegram_id):
        return True

    def _get_sender_username(self, update):
        return "admin"


def make_update():
    return SimpleNamespace(message=FakeMessage())


def make_context():
    return SimpleNamespace(
        args=[
            "BTCUSDT",
            "short",
            "80200",
            "81000",
            "81700",
            "77777",
            "75000",
            "等待回踩后执行",
        ],
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
