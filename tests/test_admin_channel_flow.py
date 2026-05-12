import asyncio
from types import SimpleNamespace

from app.bot_admin_handlers import AdminHandlersMixin
from app.database import channel_to_dict
from app.models import ChannelGroup


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return SimpleNamespace(edit_text=self.reply_text)


class FakeChannelRepo:
    def __init__(self, existing=None, deactivate_result=True):
        self.existing = existing
        self.deactivate_result = deactivate_result
        self.deactivated_chat_id = None
        self.reactivated = None
        self.created = None
        self.topic_updated = None
        self.topic_cleared_chat_id = None
        self.active_channels = [
            {
                "chat_id": "-1001",
                "title": "test_kaiyn",
                "message_thread_id": None,
                "thread_title": None,
            }
        ]

    async def deactivate_channel(self, chat_id):
        self.deactivated_chat_id = chat_id
        return self.deactivate_result

    async def get_channel_by_chat_id(self, chat_id):
        return self.existing

    async def reactivate_channel(self, **kwargs):
        self.reactivated = kwargs
        return True

    async def create_channel(self, **kwargs):
        self.created = kwargs

    async def get_active_channels(self):
        return self.active_channels

    async def update_channel_topic(self, chat_id, message_thread_id, thread_title):
        self.topic_updated = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
            "thread_title": thread_title,
        }
        return True

    async def clear_channel_topic(self, chat_id):
        self.topic_cleared_chat_id = chat_id
        return True


class FakeBot:
    def __init__(self):
        self.chat = SimpleNamespace(
            id=-1001,
            title="test_kaiyn",
            type=SimpleNamespace(value="channel"),
            username="test_kaiyn",
        )
        self.id = 99

    async def get_chat(self, chat_identifier):
        return self.chat

    async def get_chat_member(self, chat_identifier, bot_id):
        return SimpleNamespace(status="administrator")


class FakeAdminHandler(AdminHandlersMixin):
    def __init__(self, channel_repo):
        self.channel_repo = channel_repo
        self.user_sessions = {
            123: {
                "step": "delete_channel",
                "channels_data": [{"chat_id": "-1001", "title": "test_kaiyn"}],
            }
        }
        self.user = SimpleNamespace(telegram_id=123)

    async def _get_or_create_user(self, update):
        return self.user

    def _escape_html(self, text):
        return super()._escape_html(text)


def make_update(text="1"):
    return SimpleNamespace(message=FakeMessage(text))


def make_context():
    return SimpleNamespace(args=["@test_kaiyn"], bot=FakeBot())


def make_context_with_args(args):
    return SimpleNamespace(args=args, bot=FakeBot())


def test_delete_channel_success_reply_does_not_use_markdown(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("1")

    asyncio.run(handler.delete_channel_by_number(update, make_context()))

    assert channel_repo.deactivated_chat_id == "-1001"
    assert update.message.replies[-1]["text"].startswith("✅ 频道已删除")
    assert "parse_mode" not in update.message.replies[-1]["kwargs"]


def test_add_channel_reactivates_inactive_existing_channel(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    existing = SimpleNamespace(is_active=False)
    channel_repo = FakeChannelRepo(existing=existing)
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    asyncio.run(handler.add_channel_command(update, make_context()))

    assert channel_repo.created is None
    assert channel_repo.reactivated["chat_id"] == "-1001"
    assert channel_repo.reactivated["title"] == "test_kaiyn"
    assert update.message.replies[-1]["kwargs"]["parse_mode"] == "HTML"
    assert "频道/群组添加成功" in update.message.replies[-1]["text"]


def test_channel_to_dict_includes_topic_fields():
    channel = ChannelGroup(
        chat_id="-1001",
        chat_type="supergroup",
        title="test_kaiyn",
        username="test_kaiyn",
        added_by_user_id=123,
        message_thread_id=456,
        thread_title="交易信号",
    )

    result = channel_to_dict(channel)

    assert result["message_thread_id"] == 456
    assert result["thread_title"] == "交易信号"


def test_set_channel_topic_by_display_number(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    asyncio.run(
        handler.set_channel_topic_command(
            update, make_context_with_args(["1", "456", "交易信号"])
        )
    )

    assert channel_repo.topic_updated == {
        "chat_id": "-1001",
        "message_thread_id": 456,
        "thread_title": "交易信号",
    }
    assert "指定话题已设置" in update.message.replies[-1]["text"]


def test_set_channel_topic_rejects_invalid_topic_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    asyncio.run(
        handler.set_channel_topic_command(
            update, make_context_with_args(["1", "not-a-number"])
        )
    )

    assert channel_repo.topic_updated is None
    assert update.message.replies[-1]["text"] == "❌ 频道编号和 topic_id 必须是正整数"


def test_clear_channel_topic_by_display_number(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    asyncio.run(
        handler.clear_channel_topic_command(update, make_context_with_args(["1"]))
    )

    assert channel_repo.topic_cleared_chat_id == "-1001"
    assert "指定话题已清除" in update.message.replies[-1]["text"]
