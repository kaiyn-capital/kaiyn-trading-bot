from types import SimpleNamespace

import pytest
from settings_factory import make_settings

from app.bot import TelegramBot
from app.bot_admin_handlers import AdminHandlersMixin
from app.bot_admin_permissions import ADMIN_PERMISSION_DENIED_MESSAGE
from app.bot_callback_router import CallbackRoute, CallbackRouter


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append({"text": text, "kwargs": kwargs})

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, "kwargs": kwargs})


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


class FakeAdminHandler(AdminHandlersMixin):
    def __init__(self, user, settings=None):
        self.user = user
        self.settings = settings or make_settings(admin_ids=(123,))

    async def _get_or_create_user(self, update):
        return self.user


def make_update(data, *, chat_type="private", telegram_id=123):
    return SimpleNamespace(
        callback_query=FakeQuery(data),
        effective_chat=SimpleNamespace(id=telegram_id, type=chat_type),
        effective_user=SimpleNamespace(id=telegram_id),
    )


def make_user(telegram_id=123):
    return SimpleNamespace(id=1, telegram_id=telegram_id)


def make_bot(user, settings=None):
    bot = TelegramBot.__new__(TelegramBot)
    bot.settings = settings or make_settings(admin_ids=(123,))
    bot.user_sessions = {}

    async def get_user(update):
        return user

    bot._get_or_create_user = get_user
    return bot


@pytest.mark.asyncio
async def test_button_callback_dispatches_exact_callback():
    user = make_user()
    bot = make_bot(user)
    routed = []

    async def handle_status(query, callback_user):
        routed.append({"query": query, "user": callback_user})

    bot._handle_status_callback = handle_status
    update = make_update("check_status")

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert update.callback_query.answers == [{"text": None, "kwargs": {}}]
    assert routed == [{"query": update.callback_query, "user": user}]


@pytest.mark.asyncio
async def test_callback_router_dispatches_exact_and_prefix_callbacks():
    routed = []

    async def exact_handler(query, user):
        routed.append(("exact", query.data, user.telegram_id))

    async def prefix_handler(query, user, data):
        routed.append(("prefix", data, user.telegram_id))

    router = CallbackRouter(
        exact_routes={"check_status": CallbackRoute(exact_handler)},
        prefix_routes=(("confirm_order_", CallbackRoute(prefix_handler, include_data=True)),),
    )
    user = make_user()

    assert await router.dispatch(FakeQuery("check_status"), user, "check_status") is True
    assert await router.dispatch(FakeQuery("confirm_order_tok"), user, "confirm_order_tok") is True
    assert await router.dispatch(FakeQuery("unknown"), user, "unknown") is False
    assert routed == [
        ("exact", "check_status", user.telegram_id),
        ("prefix", "confirm_order_tok", user.telegram_id),
    ]


def test_callback_router_identifies_admin_only_callbacks():
    async def handler(query, user):
        return None

    router = CallbackRouter(
        exact_routes={"manage_channels": CallbackRoute(handler, admin_only=True)},
        prefix_routes=(),
    )

    assert router.is_admin_callback("manage_channels") is True
    assert router.is_admin_callback("missing") is False


@pytest.mark.asyncio
async def test_button_callback_dispatches_prefix_callbacks():
    user = make_user()
    bot = make_bot(user)
    routed = []

    async def handle_confirm(query, callback_user, data):
        routed.append({"query": query, "user": callback_user, "data": data})

    bot._handle_confirm_pending_order_callback = handle_confirm
    update = make_update("confirm_order_token")

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert update.callback_query.answers == [{"text": None, "kwargs": {}}]
    assert routed == [{"query": update.callback_query, "user": user, "data": "confirm_order_token"}]


@pytest.mark.asyncio
async def test_button_callback_dispatches_signal_preview_prefix_callbacks():
    user = make_user()
    bot = make_bot(user)
    routed = []

    async def handle_confirm_signal(query, callback_user, data):
        routed.append({"query": query, "user": callback_user, "data": data})

    bot._handle_confirm_signal_callback = handle_confirm_signal
    update = make_update("confirm_signal_token")

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert update.callback_query.answers == [{"text": None, "kwargs": {}}]
    assert routed == [{"query": update.callback_query, "user": user, "data": "confirm_signal_token"}]


@pytest.mark.asyncio
async def test_button_callback_dispatches_chart_update_preview_prefix_callbacks():
    user = make_user()
    bot = make_bot(user)
    routed = []

    async def handle_confirm_chart_update(query, callback_user, data):
        routed.append({"query": query, "user": callback_user, "data": data})

    bot._handle_confirm_chart_update_callback = handle_confirm_chart_update
    update = make_update("confirm_chart_update_token")

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert update.callback_query.answers == [{"text": None, "kwargs": {}}]
    assert routed == [{"query": update.callback_query, "user": user, "data": "confirm_chart_update_token"}]


@pytest.mark.asyncio
async def test_cancel_modify_api_callback_keeps_existing_response():
    bot = make_bot(make_user())
    update = make_update("cancel_modify_api")

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert update.callback_query.answers == [
        {"text": None, "kwargs": {}},
        {"text": "已取消", "kwargs": {}},
    ]
    assert update.callback_query.edits == [{"text": "✅ 已取消修改 API 设置", "kwargs": {}}]


@pytest.mark.asyncio
async def test_cancel_change_risk_callback_clears_session():
    user = make_user()
    bot = make_bot(user)
    bot.user_sessions = {user.telegram_id: {"step": "risk_amount"}}
    update = make_update("cancel_change_risk")

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert bot.user_sessions == {}
    assert update.callback_query.edits == [{"text": "✅ 已取消更改风险设置", "kwargs": {}}]


@pytest.mark.asyncio
async def test_cancel_order_callback_uses_private_message_wrapper():
    user = make_user()
    bot = make_bot(user)
    sent = []

    async def send_private_message(query, callback_user, text, reply_markup=None):
        sent.append(
            {
                "query": query,
                "user": callback_user,
                "text": text,
                "reply_markup": reply_markup,
            }
        )

    bot._send_private_message = send_private_message
    update = make_update("cancel_order")

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert update.callback_query.answers == [
        {"text": None, "kwargs": {}},
        {"text": "已取消下单", "kwargs": {}},
    ]
    assert sent == [
        {
            "query": update.callback_query,
            "user": user,
            "text": "✅ 已取消下单",
            "reply_markup": None,
        }
    ]


@pytest.mark.asyncio
async def test_unknown_callback_keeps_unknown_operation_message():
    bot = make_bot(make_user())
    update = make_update("unknown_callback")

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert update.callback_query.answers == [{"text": None, "kwargs": {}}]
    assert update.callback_query.edits == [{"text": "❓ 未知操作", "kwargs": {}}]


@pytest.mark.asyncio
async def test_admin_callback_rejects_non_admin_without_editing_or_session():
    user = make_user(telegram_id=123)
    bot = make_bot(user, settings=make_settings(admin_ids=(999,)))
    bot.user_sessions = {}
    update = make_update("manage_channels", telegram_id=user.telegram_id)

    await TelegramBot.button_callback(bot, update, SimpleNamespace())

    assert update.callback_query.answers == [{"text": ADMIN_PERMISSION_DENIED_MESSAGE, "kwargs": {"show_alert": True}}]
    assert update.callback_query.edits == []
    assert bot.user_sessions == {}


@pytest.mark.asyncio
async def test_require_admin_rejects_non_admin():
    handler = FakeAdminHandler(make_user(telegram_id=123), settings=make_settings(admin_ids=(999,)))
    update = SimpleNamespace(message=FakeMessage())

    result = await handler._require_admin(update)

    assert result is None
    assert update.message.replies == [{"text": ADMIN_PERMISSION_DENIED_MESSAGE, "kwargs": {}}]
