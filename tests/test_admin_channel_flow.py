import asyncio
from datetime import datetime
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


class FakeUserRepo:
    def __init__(self, set_trader_result=True):
        self.db = SimpleNamespace()
        self.set_trader_result = set_trader_result
        self.set_trader_calls = []

    async def set_trader_status(self, telegram_id, is_trader):
        self.set_trader_calls.append({"telegram_id": telegram_id, "is_trader": is_trader})
        return self.set_trader_result


class FakeSystemLogRepo:
    def __init__(self, logs=None):
        self.logs = logs or []
        self.calls = []

    async def get_recent_logs(self, **kwargs):
        self.calls.append(kwargs)
        return self.logs[: kwargs.get("limit", 10)]


class FakeBot:
    def __init__(self):
        self.chat = SimpleNamespace(
            id=-1001,
            title="test_kaiyn",
            type=SimpleNamespace(value="channel"),
            username="test_kaiyn",
        )
        self.id = 99
        self.sent_messages = []

    async def get_chat(self, chat_identifier):
        return self.chat

    async def get_chat_member(self, chat_identifier, bot_id):
        return SimpleNamespace(status="administrator")

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(message_id=len(self.sent_messages))


class FakeAdminHandler(AdminHandlersMixin):
    def __init__(self, channel_repo, system_log_repo=None, user_repo=None):
        self.channel_repo = channel_repo
        self.user_sessions = {
            123: {
                "step": "delete_channel",
                "channels_data": [{"chat_id": "-1001", "title": "test_kaiyn"}],
            }
        }
        self.user = SimpleNamespace(telegram_id=123)
        self.user_repo = user_repo or FakeUserRepo()
        self.system_log_repo = system_log_repo or FakeSystemLogRepo()
        self.started_at = None
        self.audit_events = []

    async def _get_or_create_user(self, update):
        return self.user

    async def _audit_action(self, user, action, details=None):
        self.audit_events.append({"telegram_id": user.telegram_id, "action": action, "details": details or {}})

    def _get_sender_username(self, update):
        return "admin"

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
    assert handler.audit_events[-1]["action"] == "admin_delete_channel"
    assert handler.audit_events[-1]["details"]["status"] == "success"


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
    assert handler.audit_events[-1]["action"] == "admin_add_channel"
    assert handler.audit_events[-1]["details"]["status"] == "reactivated"


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

    asyncio.run(handler.set_channel_topic_command(update, make_context_with_args(["1", "456", "交易信号"])))

    assert channel_repo.topic_updated == {
        "chat_id": "-1001",
        "message_thread_id": 456,
        "thread_title": "交易信号",
    }
    assert "指定话题已设置" in update.message.replies[-1]["text"]
    assert handler.audit_events[-1]["action"] == "admin_set_channel_topic"
    assert handler.audit_events[-1]["details"]["message_thread_id"] == 456


def test_set_channel_topic_rejects_invalid_topic_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    asyncio.run(handler.set_channel_topic_command(update, make_context_with_args(["1", "not-a-number"])))

    assert channel_repo.topic_updated is None
    assert update.message.replies[-1]["text"] == "❌ 频道编号和 topic_id 必须是正整数"
    assert handler.audit_events[-1]["action"] == "admin_set_channel_topic"
    assert handler.audit_events[-1]["details"]["status"] == "failed"


def test_clear_channel_topic_by_display_number(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    asyncio.run(handler.clear_channel_topic_command(update, make_context_with_args(["1"])))

    assert channel_repo.topic_cleared_chat_id == "-1001"
    assert "指定话题已清除" in update.message.replies[-1]["text"]
    assert handler.audit_events[-1]["action"] == "admin_clear_channel_topic"
    assert handler.audit_events[-1]["details"]["status"] == "success"


def test_add_trader_success_is_audited(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    user_repo = FakeUserRepo(set_trader_result=True)
    handler = FakeAdminHandler(FakeChannelRepo(), user_repo=user_repo)
    update = make_update("")

    asyncio.run(handler.add_trader_command(update, make_context_with_args(["456"])))

    assert user_repo.set_trader_calls == [{"telegram_id": 456, "is_trader": True}]
    assert handler.audit_events[-1]["action"] == "admin_add_trader"
    assert handler.audit_events[-1]["details"] == {
        "status": "success",
        "target_telegram_id": 456,
    }


def test_admin_broadcast_records_summary_audit(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    handler = FakeAdminHandler(FakeChannelRepo())
    update = make_update("")
    context = make_context_with_args(["系统维护", "请稍候"])

    asyncio.run(handler.admin_broadcast_command(update, context))

    audit = handler.audit_events[-1]
    assert audit["action"] == "admin_broadcast"
    assert audit["details"]["target_count"] == 1
    assert audit["details"]["sent_count"] == 1
    assert audit["details"]["message"]["length"] == len("系统维护 请稍候")


def test_admin_audit_rejects_non_admin(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "999")
    handler = FakeAdminHandler(FakeChannelRepo())
    update = make_update("")

    asyncio.run(handler.admin_audit_command(update, make_context_with_args([])))

    assert update.message.replies[-1]["text"] == "❌ 您没有管理员权限"


def test_admin_audit_shows_recent_audit_logs(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    system_log_repo = FakeSystemLogRepo(
        logs=[
            SimpleNamespace(
                created_at=datetime(2026, 5, 12, 1, 2, 3),
                function="signal_sent",
                telegram_id=123,
                extra_data={
                    "status": "completed",
                    "symbol": "BTCUSDT",
                    "target_count": 1,
                    "sent_count": 1,
                },
            )
        ]
    )
    handler = FakeAdminHandler(FakeChannelRepo(), system_log_repo=system_log_repo)
    update = make_update("")

    asyncio.run(handler.admin_audit_command(update, make_context_with_args(["50"])))

    assert system_log_repo.calls[-1]["module"] == "audit"
    assert system_log_repo.calls[-1]["limit"] == 30
    assert "近期操作审计" in update.message.replies[-1]["text"]
    assert "signal_sent" in update.message.replies[-1]["text"]


def test_admin_health_rejects_non_admin(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "999")
    handler = FakeAdminHandler(FakeChannelRepo())
    update = make_update("")

    asyncio.run(handler.admin_health_command(update, make_context()))

    assert update.message.replies[-1]["text"] == "❌ 您没有管理员权限"


def test_admin_health_replies_report(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")

    async def fake_build_admin_health_report(**kwargs):
        return "🩺 **系统健康检查**\n\nDB：✅ 正常", {"db_ok": True}

    monkeypatch.setattr(
        "app.bot_admin_monitoring.build_admin_health_report",
        fake_build_admin_health_report,
    )
    handler = FakeAdminHandler(FakeChannelRepo())
    update = make_update("")

    asyncio.run(handler.admin_health_command(update, make_context()))

    assert "系统健康检查" in update.message.replies[-1]["text"]
    assert update.message.replies[-1]["kwargs"]["parse_mode"] == "Markdown"
