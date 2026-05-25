from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from settings_factory import make_settings

from app.bot_admin_handlers import AdminHandlersMixin
from app.bot_handler_context import BotHandlerContext
from app.bot_sessions import SESSION_EXPIRED_MESSAGE
from app.models import ChannelGroup
from app.repositories.channels import channel_record_from_model
from app.repository_types import ChannelRecord
from app.session_types import ChannelManagementSession


def make_channel_record(**overrides):
    data = {
        "id": 1,
        "chat_id": "-1001",
        "chat_type": "channel",
        "title": "test_kaiyn",
        "username": "test_kaiyn",
        "is_active": True,
        "auto_forward_signals": True,
        "forward_with_buttons": True,
        "message_thread_id": None,
        "thread_title": None,
        "added_by_user_id": 123,
        "description": None,
        "created_at": None,
        "updated_at": None,
    }
    data.update(overrides)
    return ChannelRecord(**data)


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return SimpleNamespace(edit_text=self.reply_text)


class FakeQuery:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, "kwargs": kwargs})


class FakeChannelRepo:
    def __init__(self, existing=None, deactivate_result=True):
        self.existing = existing
        self.deactivate_result = deactivate_result
        self.deactivated_chat_id = None
        self.reactivated = None
        self.created = None
        self.topic_updated = None
        self.topic_cleared_chat_id = None
        self.active_channels = [make_channel_record()]

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
        return make_channel_record(**kwargs)

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
    def __init__(self, channel_repo, system_log_repo=None, user_repo=None, settings=None):
        self.channel_repo = channel_repo
        self.settings = settings or make_settings(admin_ids=(123,))
        self.user_sessions = {}
        self.now = datetime(2026, 5, 18, 12, 0, 0)
        self.user = SimpleNamespace(telegram_id=123)
        self.user_repo = user_repo or FakeUserRepo()
        self.system_log_repo = system_log_repo or FakeSystemLogRepo()
        self.started_at = None
        self.audit_events = []

    async def _get_or_create_user(self, update):
        return self.user

    def _session_now(self):
        return self.now

    async def _audit_action(self, user, action, details=None):
        self.audit_events.append({"telegram_id": user.telegram_id, "action": action, "details": details or {}})

    def _get_sender_username(self, update):
        return "admin"


def make_update(text="1"):
    return SimpleNamespace(message=FakeMessage(text))


def make_context():
    return SimpleNamespace(args=["@test_kaiyn"], bot=FakeBot())


def make_context_with_args(args):
    return SimpleNamespace(args=args, bot=FakeBot())


@pytest.mark.asyncio
async def test_handler_context_delegates_active_channel_lookup():
    class Owner:
        def __init__(self):
            self.calls = []
            self.user_session_repo = object()

        async def _get_active_channel_by_number(self, channel_number):
            self.calls.append(channel_number)
            return make_channel_record(id=channel_number)

    owner = Owner()
    context = BotHandlerContext(owner)

    channel = await context._get_active_channel_by_number(2)

    assert owner.calls == [2]
    assert channel.id == 2
    assert context.user_session_repo is owner.user_session_repo


@pytest.mark.asyncio
async def test_delete_channel_success_reply_uses_html():
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    await handler.set_user_session(
        123,
        ChannelManagementSession(
            step="delete_channel",
            channels_data=[{"chat_id": "-1001", "title": "test_kaiyn"}],
        ),
    )
    update = make_update("1")

    await handler.delete_channel_by_number(update, make_context())

    assert channel_repo.deactivated_chat_id == "-1001"
    assert update.message.replies[-1]["text"].startswith("✅ 频道已删除")
    assert update.message.replies[-1]["kwargs"]["parse_mode"] == "HTML"
    assert handler.audit_events[-1]["action"] == "admin_delete_channel"
    assert handler.audit_events[-1]["details"]["status"] == "success"


@pytest.mark.asyncio
async def test_expired_delete_channel_session_does_not_delete():
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    await handler.set_user_session(
        123,
        ChannelManagementSession(
            step="delete_channel",
            channels_data=[{"chat_id": "-1001", "title": "test_kaiyn"}],
        ),
    )
    handler.now = handler.now + timedelta(seconds=301)
    update = make_update("1")

    await handler.delete_channel_by_number(update, make_context())

    assert channel_repo.deactivated_chat_id is None
    assert handler.user_sessions == {}
    assert update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]


@pytest.mark.asyncio
async def test_expired_channel_data_does_not_enter_delete_number_flow():
    handler = FakeAdminHandler(FakeChannelRepo())
    await handler.set_user_session(
        123,
        ChannelManagementSession(channels_data=[{"chat_id": "-1001", "title": "test_kaiyn"}]),
    )
    handler.now = handler.now + timedelta(seconds=301)
    query = FakeQuery()

    await handler._handle_delete_channel_start_callback(query, handler.user)

    assert handler.user_sessions == {}
    assert query.edits == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]


@pytest.mark.asyncio
async def test_admin_channels_command_returns_html_and_keyboard():
    handler = FakeAdminHandler(FakeChannelRepo())
    update = make_update("")

    await handler.admin_channels_command(update, make_context())

    reply = update.message.replies[-1]
    assert reply["kwargs"]["parse_mode"] == "HTML"
    assert reply["kwargs"]["reply_markup"].inline_keyboard[0][0].callback_data == "add_new_channel"
    assert "📺 <b>已管理的频道/群组</b>" in reply["text"]
    assert "<b>test_kaiyn</b>" in reply["text"]
    assert "ID: <code>-1001</code>" in reply["text"]
    assert "指定话题: 未设置" in reply["text"]


@pytest.mark.asyncio
async def test_manage_channels_callback_sets_session_and_returns_keyboard():
    handler = FakeAdminHandler(FakeChannelRepo())
    query = FakeQuery()

    await handler._handle_manage_channels_callback(query, handler.user)

    session = await handler.get_active_user_session(handler.user.telegram_id)
    assert session["channels_data"] == [
        {
            "id": 1,
            "chat_id": "-1001",
            "title": "test_kaiyn",
            "username": "test_kaiyn",
        }
    ]
    edit = query.edits[-1]
    assert edit["kwargs"]["parse_mode"] == "HTML"
    assert edit["kwargs"]["reply_markup"].inline_keyboard[0][0].callback_data == "delete_channel_start"
    assert "📺 <b>管理频道</b>" in edit["text"]
    assert "1. test_kaiyn (@test_kaiyn)" in edit["text"]


@pytest.mark.asyncio
async def test_add_channel_reactivates_inactive_existing_channel():
    existing = SimpleNamespace(is_active=False)
    channel_repo = FakeChannelRepo(existing=existing)
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    await handler.add_channel_command(update, make_context())

    assert channel_repo.created is None
    assert channel_repo.reactivated["chat_id"] == "-1001"
    assert channel_repo.reactivated["title"] == "test_kaiyn"
    assert update.message.replies[-1]["kwargs"]["parse_mode"] == "HTML"
    assert "频道/群组添加成功" in update.message.replies[-1]["text"]
    assert handler.audit_events[-1]["action"] == "admin_add_channel"
    assert handler.audit_events[-1]["details"]["status"] == "reactivated"


def test_channel_record_from_model_includes_topic_fields():
    channel = ChannelGroup(
        chat_id="-1001",
        chat_type="supergroup",
        title="test_kaiyn",
        username="test_kaiyn",
        added_by_user_id=123,
        message_thread_id=456,
        thread_title="交易信号",
    )

    result = channel_record_from_model(channel)

    assert result.message_thread_id == 456
    assert result.thread_title == "交易信号"


@pytest.mark.asyncio
async def test_set_channel_topic_by_display_number():
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    await handler.set_channel_topic_command(update, make_context_with_args(["1", "456", "交易信号"]))

    assert channel_repo.topic_updated == {
        "chat_id": "-1001",
        "message_thread_id": 456,
        "thread_title": "交易信号",
    }
    assert "指定话题已设置" in update.message.replies[-1]["text"]
    assert handler.audit_events[-1]["action"] == "admin_set_channel_topic"
    assert handler.audit_events[-1]["details"]["message_thread_id"] == 456


@pytest.mark.asyncio
async def test_set_channel_topic_rejects_invalid_topic_id():
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    await handler.set_channel_topic_command(update, make_context_with_args(["1", "not-a-number"]))

    assert channel_repo.topic_updated is None
    assert update.message.replies[-1]["text"] == "❌ 频道编号和 topic_id 必须是正整数"
    assert handler.audit_events[-1]["action"] == "admin_set_channel_topic"
    assert handler.audit_events[-1]["details"]["status"] == "failed"


@pytest.mark.asyncio
async def test_clear_channel_topic_by_display_number():
    channel_repo = FakeChannelRepo()
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")

    await handler.clear_channel_topic_command(update, make_context_with_args(["1"]))

    assert channel_repo.topic_cleared_chat_id == "-1001"
    assert "指定话题已清除" in update.message.replies[-1]["text"]
    assert handler.audit_events[-1]["action"] == "admin_clear_channel_topic"
    assert handler.audit_events[-1]["details"]["status"] == "success"


@pytest.mark.asyncio
async def test_add_trader_success_is_audited():
    user_repo = FakeUserRepo(set_trader_result=True)
    handler = FakeAdminHandler(FakeChannelRepo(), user_repo=user_repo)
    update = make_update("")

    await handler.add_trader_command(update, make_context_with_args(["456"]))

    assert user_repo.set_trader_calls == [{"telegram_id": 456, "is_trader": True}]
    assert handler.audit_events[-1]["action"] == "admin_add_trader"
    assert handler.audit_events[-1]["details"] == {
        "status": "success",
        "target_telegram_id": 456,
    }


@pytest.mark.asyncio
async def test_admin_broadcast_records_summary_audit():
    handler = FakeAdminHandler(FakeChannelRepo())
    update = make_update("")
    context = make_context_with_args(["<b>系统维护</b>", "请稍候"])

    await handler.admin_broadcast_command(update, context)

    audit = handler.audit_events[-1]
    assert audit["action"] == "admin_broadcast"
    assert audit["details"]["target_count"] == 1
    assert audit["details"]["sent_count"] == 1
    assert audit["details"]["message"]["length"] == len("<b>系统维护</b> 请稍候")
    assert "message_thread_id" not in context.bot.sent_messages[-1]
    assert context.bot.sent_messages[-1]["parse_mode"] == "HTML"
    assert "&lt;b&gt;系统维护&lt;/b&gt; 请稍候" in context.bot.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_admin_broadcast_uses_configured_channel_topic():
    channel_repo = FakeChannelRepo()
    channel_repo.active_channels = [make_channel_record(message_thread_id=456)]
    handler = FakeAdminHandler(channel_repo)
    update = make_update("")
    context = make_context_with_args(["系统维护"])

    await handler.admin_broadcast_command(update, context)

    assert context.bot.sent_messages[-1]["message_thread_id"] == 456


@pytest.mark.asyncio
async def test_admin_broadcast_sends_to_message_thread_id():
    repo = FakeChannelRepo()
    repo.active_channels = [make_channel_record(message_thread_id=42, thread_title="Alerts")]
    handler = FakeAdminHandler(repo)
    update = make_update("")
    context = make_context_with_args(["系统维护", "请稍候"])

    await handler.admin_broadcast_command(update, context)

    sent = context.bot.sent_messages[0]
    assert sent["chat_id"] == "-1001"
    assert sent["message_thread_id"] == 42
    assert "系统维护 请稍候" in sent["text"]
    assert sent["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_to_channel_treats_free_text_as_plain_text():
    handler = FakeAdminHandler(FakeChannelRepo())
    update = make_update("")
    context = make_context_with_args(["@test_kaiyn", "<b>公告</b>", "&", "maintenance"])

    await handler.send_to_channel_command(update, context)

    sent = context.bot.sent_messages[0]
    assert sent["chat_id"] == "@test_kaiyn"
    assert sent["text"] == "&lt;b&gt;公告&lt;/b&gt; &amp; maintenance"
    assert sent["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_admin_audit_rejects_non_admin():
    handler = FakeAdminHandler(FakeChannelRepo(), settings=make_settings(admin_ids=(999,)))
    update = make_update("")

    await handler.admin_audit_command(update, make_context_with_args([]))

    assert update.message.replies[-1]["text"] == "❌ 您没有管理员权限"


@pytest.mark.asyncio
async def test_admin_audit_shows_recent_audit_logs():
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

    await handler.admin_audit_command(update, make_context_with_args(["50"]))

    assert system_log_repo.calls[-1]["module"] == "audit"
    assert system_log_repo.calls[-1]["limit"] == 30
    assert "近期操作审计" in update.message.replies[-1]["text"]
    assert "signal_sent" in update.message.replies[-1]["text"]


@pytest.mark.asyncio
async def test_admin_health_rejects_non_admin():
    handler = FakeAdminHandler(FakeChannelRepo(), settings=make_settings(admin_ids=(999,)))
    update = make_update("")

    await handler.admin_health_command(update, make_context())

    assert update.message.replies[-1]["text"] == "❌ 您没有管理员权限"


@pytest.mark.asyncio
async def test_admin_health_replies_report(monkeypatch):
    async def fake_build_admin_health_report(**kwargs):
        return "🩺 <b>系统健康检查</b>\n\nDB：✅ 正常", {"db_ok": True}

    monkeypatch.setattr(
        "app.bot_admin_monitoring.build_admin_health_report",
        fake_build_admin_health_report,
    )
    handler = FakeAdminHandler(FakeChannelRepo())
    update = make_update("")

    await handler.admin_health_command(update, make_context())

    assert "系统健康检查" in update.message.replies[-1]["text"]
    assert update.message.replies[-1]["kwargs"]["parse_mode"] == "HTML"
